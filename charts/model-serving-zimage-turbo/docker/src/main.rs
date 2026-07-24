//! Z-Image-Turbo inference server — Rust + Candle + Actix-web.
//!
//! Replaces the Python FastAPI server with a Rust binary for smaller image
//! size, faster startup, and better memory safety.
//!
//! # Memory optimisation for RTX A2000 (12 GB VRAM)
//!
//! See [`inference::engine`] for details on the memory management strategy.
//!
//! # Usage
//!
//! ```bash
//! export MODEL_DIR=/mnt/models
//! cargo run --release --features cuda
//! ```
//!
//! # Endpoints
//!
//! - `GET  /health`                 — health check
//! - `GET  /v1/models`              — list available models
//! - `POST /v1/images/generations`  — generate image(s)

mod api;
mod config;
mod error;
mod inference;

use actix_cors::Cors;
use actix_web::{web, App, HttpServer, middleware};
use clap::Parser;
use std::sync::Mutex;
use tracing::{info, warn};

use crate::api::routes::{AppState, generate_images, health, list_models};
use crate::config::Config;
use crate::error::ServerError;

#[actix_web::main]
async fn main() -> Result<(), ServerError> {
    // ── Parse configuration ───────────────────────────────────────────────
    let config = Config::parse();
    config.validate().map_err(ServerError::Config)?;

    // ── Initialise logging ────────────────────────────────────────────────
    let log_level = if config.verbose { "debug" } else { "info" };
    tracing_subscriber::fmt()
        .with_env_filter(format!("zimage_turbo_server={log_level},actix_web=info"))
        .with_target(true)
        .init();

    info!(
        port = config.port,
        model_dir = %config.model_dir.display(),
        max_size = config.max_image_size,
        flash_attn = config.flash_attn,
        cpu = config.cpu,
        "Starting Z-Image-Turbo server"
    );

    // ── Pre-warm: check model directory exists ────────────────────────────
    if !config.model_dir.exists() {
        warn!(
            "Model directory {} does not exist yet — will fail on first request",
            config.model_dir.display()
        );
    }

    // ── Build shared state (model loaded lazily on first request) ─────────
    let state = web::Data::new(AppState {
        engine: Mutex::new(None),
        config: config.clone(),
    });

    // ── Start HTTP server ─────────────────────────────────────────────────
    let bind_addr = format!("{}:{}", config.host, config.port);
    info!("Binding to {bind_addr}");

    let server = HttpServer::new(move || {
        let cors = Cors::default()
            .allow_any_origin()
            .allow_any_method()
            .allow_any_header()
            .max_age(3600);

        App::new()
            .wrap(cors)
            .wrap(middleware::Compress::default())
            .wrap(middleware::Logger::default())
            // Shared state
            .app_data(state.clone())
            .app_data(
                web::JsonConfig::default()
                    .limit(10 * 1024 * 1024) // 10 MB max body
                    .error_handler(|err, _| {
                        let msg = format!("Invalid JSON body: {err}");
                        actix_web::error::InternalError::from_response(
                            err,
                            actix_web::HttpResponse::BadRequest().json(serde_json::json!({
                                "error": {
                                    "code": "bad_request",
                                    "message": msg,
                                    "type": "invalid_request_error"
                                }
                            })),
                        )
                        .into()
                    }),
            )
            // Routes
            .route("/health", web::get().to(health))
            .route("/v1/models", web::get().to(list_models))
            .route("/v1/images/generations", web::post().to(generate_images))
    })
    .bind(&bind_addr)
    .map_err(|e| ServerError::Internal(format!("Failed to bind to {bind_addr}: {e}")))?
    .workers(num_workers())
    .run();

    info!("Server started");

    // Graceful shutdown on Ctrl+C
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("Failed to install Ctrl+C handler");
        info!("Shutdown signal received");
    };

    let _ = tokio::join!(server, ctrl_c);

    info!("Server stopped");
    Ok(())
}

/// Determine the number of Actix worker threads.
///
/// Uses available CPU cores, capped at 4 for GPU-bound workloads (inference
/// is GPU-bound, so more workers just add contention on the model Mutex).
fn num_workers() -> usize {
    let cores = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4);
    cores.clamp(1, 4)
}
