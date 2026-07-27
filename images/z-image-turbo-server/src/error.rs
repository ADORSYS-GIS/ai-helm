//! Unified error types with automatic HTTP status mapping for Actix-web.

use actix_web::{HttpResponse, ResponseError};
use std::fmt;

/// All server-level errors, categorised by origin.
#[derive(Debug)]
#[allow(dead_code)]
pub enum ServerError {
    /// Configuration error (missing env var, bad value).
    Config(String),
    /// Model loading failure.
    ModelLoad(String),
    /// Inference failure (OOM, tensor shape mismatch, etc.).
    Inference(String),
    /// Authentication failure.
    Unauthorized(String),
    /// Invalid request from client.
    BadRequest(String),
    /// Resource not found.
    NotFound(String),
    /// Internal error not covered above.
    Internal(String),
}

impl fmt::Display for ServerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Config(msg) => write!(f, "Configuration error: {msg}"),
            Self::ModelLoad(msg) => write!(f, "Model loading error: {msg}"),
            Self::Inference(msg) => write!(f, "Inference error: {msg}"),
            Self::Unauthorized(msg) => write!(f, "Unauthorized: {msg}"),
            Self::BadRequest(msg) => write!(f, "Bad request: {msg}"),
            Self::NotFound(msg) => write!(f, "Not found: {msg}"),
            Self::Internal(msg) => write!(f, "Internal error: {msg}"),
        }
    }
}

impl ResponseError for ServerError {
    fn error_response(&self) -> HttpResponse {
        let (status, code, error_type) = match self {
            Self::Config(_) | Self::Internal(_) => {
                (actix_web::http::StatusCode::INTERNAL_SERVER_ERROR, "internal_error", "config_error")
            }
            Self::ModelLoad(_) => {
                (actix_web::http::StatusCode::SERVICE_UNAVAILABLE, "model_load_error", "model_load_error")
            }
            Self::Inference(_) => {
                (actix_web::http::StatusCode::INTERNAL_SERVER_ERROR, "inference_error", "inference_error")
            }
            Self::Unauthorized(_) => {
                (actix_web::http::StatusCode::UNAUTHORIZED, "unauthorized", "auth_error")
            }
            Self::BadRequest(_) => {
                (actix_web::http::StatusCode::BAD_REQUEST, "bad_request", "invalid_request_error")
            }
            Self::NotFound(_) => {
                (actix_web::http::StatusCode::NOT_FOUND, "not_found", "not_found")
            }
        };

        let message = match self {
            Self::Config(m) | Self::ModelLoad(m) | Self::Inference(m)
                | Self::Unauthorized(m) | Self::BadRequest(m) | Self::NotFound(m)
                | Self::Internal(m) => m.clone(),
        };

        HttpResponse::build(status).json(serde_json::json!({
            "error": {
                "code": code,
                "message": message,
                "type": error_type,
            }
        }))
    }
}

impl From<anyhow::Error> for ServerError {
    fn from(e: anyhow::Error) -> Self {
        Self::Internal(e.to_string())
    }
}

impl From<candle_core::Error> for ServerError {
    fn from(e: candle_core::Error) -> Self {
        Self::Inference(e.to_string())
    }
}

impl From<std::io::Error> for ServerError {
    fn from(e: std::io::Error) -> Self {
        Self::Internal(e.to_string())
    }
}

impl From<serde_json::Error> for ServerError {
    fn from(e: serde_json::Error) -> Self {
        Self::BadRequest(e.to_string())
    }
}

impl From<tokenizers::Error> for ServerError {
    fn from(e: tokenizers::Error) -> Self {
        Self::Inference(format!("Tokenizer error: {e}"))
    }
}

impl From<image::ImageError> for ServerError {
    fn from(e: image::ImageError) -> Self {
        Self::Internal(format!("Image error: {e}"))
    }
}
