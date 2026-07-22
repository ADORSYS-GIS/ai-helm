//! Actix-web route handlers for the Z-Image-Turbo server.

use actix_web::{web, HttpResponse};
use base64::Engine;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::api::models::{
    GenerateRequest, GenerateResponse, HealthResponse, ImageData, ModelEntry,
    ModelListResponse,
};
use crate::config::Config;
use crate::inference::engine::InferenceEngine;
use crate::ServerError;

/// Shared application state.
pub struct AppState {
    /// Lazy-loaded inference engine (protected by a mutex for thread safety).
    pub engine: Mutex<Option<InferenceEngine>>,
    /// Server configuration.
    pub config: Config,
}

/// GET /health — lightweight health check.
///
/// Returns 200 only when the inference engine is loaded and ready.
/// Returns 503 (Service Unavailable) while the model is still loading,
/// so the readiness probe can correctly gate traffic.
pub async fn health(data: web::Data<AppState>) -> HttpResponse {
    let engine_loaded = data.engine.lock()
        .ok()
        .map(|guard| guard.is_some())
        .unwrap_or(false);
    let device = if data.config.cpu { "cpu" } else { "cuda" };

    if engine_loaded {
        HttpResponse::Ok().json(HealthResponse {
            status: "ok".into(),
            device: device.into(),
            model_loaded: true,
            version: env!("CARGO_PKG_VERSION"),
        })
    } else {
        HttpResponse::ServiceUnavailable().json(HealthResponse {
            status: "model_loading".into(),
            device: device.into(),
            model_loaded: false,
            version: env!("CARGO_PKG_VERSION"),
        })
    }
}

/// GET /v1/models — list available models (OpenAI-compatible).
pub async fn list_models() -> HttpResponse {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    HttpResponse::Ok().json(ModelListResponse {
        object: "list".into(),
        data: vec![ModelEntry {
            id: "z-image-turbo".into(),
            object: "model".into(),
            created: now,
            owned_by: "adorsys-gis".into(),
        }],
    })
}

/// POST /v1/images/generations — generate image(s) from a text prompt.
pub async fn generate_images(
    data: web::Data<AppState>,
    body: web::Json<GenerateRequest>,
) -> Result<HttpResponse, ServerError> {
    let cfg = &data.config;

    let req = body.into_inner();

    // ── Validate request ──────────────────────────────────────────────────
    if req.prompt.trim().is_empty() {
        return Err(ServerError::BadRequest("prompt is required".into()));
    }

    let n = req.n.clamp(1, 4);
    let (width, height) = req
        .parse_size(cfg.max_image_size)
        .ok_or_else(|| {
            ServerError::BadRequest(format!(
                "Invalid size '{}'. Must be WxH with both dimensions ≤ {} and divisible by 16. \
                 Examples: 1024x1024, 768x768, 512x512",
                req.size, cfg.max_image_size
            ))
        })?;

    if req.response_format != "b64_json" {
        return Err(ServerError::BadRequest(
            "Only 'b64_json' response_format is supported".into(),
        ));
    }

    // ── Run inference ─────────────────────────────────────────────────────
    let created = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    // Acquire the model lock and run inference.
    // `web::block` runs the synchronous inference on the Actix blocking thread pool,
    // preventing the async runtime from being blocked by CUDA kernel execution.
    let config_clone = cfg.clone();
    let prompt = req.prompt.clone();

    let images = web::block(move || -> Result<Vec<Vec<u8>>, ServerError> {
        let mut guard = data.engine.lock().map_err(|e| {
            ServerError::Internal(format!("Failed to acquire model lock: {e}"))
        })?;

        // Lazy-load the model on first request.
        if guard.is_none() {
            match InferenceEngine::load(&config_clone) {
                Ok(engine) => *guard = Some(engine),
                Err(e) => return Err(ServerError::ModelLoad(e.to_string())),
            }
        }
        let engine = guard.as_ref().unwrap();

        engine.generate(&prompt, n, width, height, &config_clone)
    })
    .await
    .map_err(|e| ServerError::Internal(format!("Blocking task failed: {e}")))??;

    // ── Encode to base64 ──────────────────────────────────────────────────
    let data: Vec<ImageData> = images
        .into_iter()
        .map(|png_bytes| ImageData {
            b64_json: Some(base64::engine::general_purpose::STANDARD.encode(&png_bytes)),
            url: None,
            revised_prompt: None,
        })
        .collect();

    Ok(HttpResponse::Ok().json(GenerateResponse { created, data }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{test, web, App};
    use clap::Parser;
    use serde_json::Value;

    #[actix_web::test]
    async fn test_health_endpoint() {
        let cfg = Config::parse_from(&["test", "--model-dir", "/tmp"]);
        let state = web::Data::new(AppState {
            engine: Mutex::new(None),
            config: cfg,
        });

        let app = test::init_service(
            App::new()
                .app_data(state.clone())
                .route("/health", web::get().to(health)),
        )
        .await;

        let req = test::TestRequest::get().uri("/health").to_request();
        let resp = test::call_service(&app, req).await;
        // When no model is loaded, health returns 503 Service Unavailable
        assert_eq!(resp.status(), actix_web::http::StatusCode::SERVICE_UNAVAILABLE);

        let body: Value = test::read_body_json(resp).await;
        assert_eq!(body["status"], "model_loading");
        assert_eq!(body["model_loaded"], false);
    }

    #[actix_web::test]
    async fn test_list_models() {
        let app = test::init_service(
            App::new().route("/v1/models", web::get().to(list_models)),
        )
        .await;

        let req = test::TestRequest::get().uri("/v1/models").to_request();
        let resp = test::call_service(&app, req).await;
        assert!(resp.status().is_success());

        let body: Value = test::read_body_json(resp).await;
        assert_eq!(body["object"], "list");
        assert_eq!(body["data"].as_array().unwrap().len(), 1);
        assert_eq!(body["data"][0]["id"], "z-image-turbo");
    }

    #[actix_web::test]
    async fn test_generate_with_empty_prompt() {
        let cfg = Config::parse_from(&["test", "--model-dir", "/tmp"]);
        let state = web::Data::new(AppState {
            engine: Mutex::new(None),
            config: cfg,
        });

        let app = test::init_service(
            App::new()
                .app_data(state.clone())
                .route("/v1/images/generations", web::post().to(generate_images)),
        )
        .await;

        let req = test::TestRequest::post()
            .uri("/v1/images/generations")
            .set_json(serde_json::json!({"prompt": ""}))
            .to_request();
        let resp = test::call_service(&app, req).await;
        assert_eq!(resp.status(), 400);
    }

    #[actix_web::test]
    async fn test_generate_with_invalid_size() {
        let cfg = Config::parse_from(&["test", "--model-dir", "/tmp"]);
        let state = web::Data::new(AppState {
            engine: Mutex::new(None),
            config: cfg,
        });

        let app = test::init_service(
            App::new()
                .app_data(state.clone())
                .route("/v1/images/generations", web::post().to(generate_images)),
        )
        .await;

        let req = test::TestRequest::post()
            .uri("/v1/images/generations")
            .set_json(serde_json::json!({"prompt": "test", "size": "invalid"}))
            .to_request();
        let resp = test::call_service(&app, req).await;
        assert_eq!(resp.status(), 400);
    }
}
