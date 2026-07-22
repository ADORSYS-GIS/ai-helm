//! OpenAI-compatible request/response types for `/v1/images/generations`.

use serde::{Deserialize, Serialize};

// ── OpenAI-compatible request ─────────────────────────────────────────────

/// POST /v1/images/generations request body.
///
/// Follows the OpenAI API shape: <https://platform.openai.com/docs/api-reference/images/create>
#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
#[allow(dead_code)]
pub struct GenerateRequest {
    /// Text prompt for image generation.
    pub prompt: String,

    /// Model name (ignored by this server, present for OpenAI client compatibility).
    pub model: Option<String>,

    /// Number of images to generate (1–4).
    #[serde(default = "default_n")]
    pub n: u32,

    /// Image size as "{width}x{height}" string.
    /// E.g. "1024x1024", "768x768", "512x512".
    #[serde(default = "default_size")]
    pub size: String,

    /// Response format: "b64_json" or "url".
    /// This server only supports "b64_json".
    #[serde(default = "default_response_format")]
    pub response_format: String,

    /// Ignored (OpenAI compatibility field).
    pub quality: Option<String>,

    /// Ignored (OpenAI compatibility field).
    pub style: Option<String>,

    /// User identifier (OpenAI compatibility).
    pub user: Option<String>,
}

fn default_n() -> u32 {
    1
}
fn default_size() -> String {
    "1024x1024".into()
}
fn default_response_format() -> String {
    "b64_json".into()
}

impl GenerateRequest {
    /// Parse the `size` field into (width, height).
    /// Returns None if the format is invalid or dimensions exceed limits.
    pub fn parse_size(&self, max_size: usize) -> Option<(usize, usize)> {
        let parts: Vec<&str> = self.size.split('x').collect();
        if parts.len() != 2 {
            return None;
        }
        let w: usize = parts[0].parse().ok()?;
        let h: usize = parts[1].parse().ok()?;
        if w == 0 || h == 0 || w > max_size || h > max_size {
            return None;
        }
        if w % 16 != 0 || h % 16 != 0 {
            return None;
        }
        Some((w, h))
    }
}

// ── OpenAI-compatible response ────────────────────────────────────────────

/// Single image data within the response.
#[derive(Debug, Serialize)]
pub struct ImageData {
    /// Base64-encoded PNG image data.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub b64_json: Option<String>,

    /// URL to the generated image (not used by this server).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,

    /// The revised prompt (not used by this server).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub revised_prompt: Option<String>,
}

/// POST /v1/images/generations response.
#[derive(Debug, Serialize)]
pub struct GenerateResponse {
    pub created: u64,
    pub data: Vec<ImageData>,
}

// ── Health check ──────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct HealthResponse {
    pub status: String,
    pub device: String,
    pub model_loaded: bool,
    pub version: &'static str,
}

// ── Model listing ─────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct ModelEntry {
    pub id: String,
    pub object: String,
    pub created: u64,
    pub owned_by: String,
}

#[derive(Debug, Serialize)]
pub struct ModelListResponse {
    pub object: String,
    pub data: Vec<ModelEntry>,
}

// ── Error response ────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
#[allow(dead_code)]
pub struct ErrorDetail {
    pub code: String,
    pub message: String,
    #[serde(rename = "type")]
    pub error_type: String,
}

#[derive(Debug, Serialize)]
#[allow(dead_code)]
pub struct ErrorResponse {
    pub error: ErrorDetail,
}

// ── Tests ─────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_size_valid() {
        let req = GenerateRequest {
            prompt: "test".into(),
            model: None,
            n: 1,
            size: "1024x1024".into(),
            response_format: "b64_json".into(),
            quality: None,
            style: None,
            user: None,
        };
        assert_eq!(req.parse_size(2048), Some((1024, 1024)));
    }

    #[test]
    fn test_parse_size_invalid_format() {
        let req = GenerateRequest {
            size: "square".into(),
            ..generate_req_default()
        };
        assert_eq!(req.parse_size(1024), None);
    }

    #[test]
    fn test_parse_size_exceeds_max() {
        let req = GenerateRequest {
            size: "2048x2048".into(),
            ..generate_req_default()
        };
        assert_eq!(req.parse_size(1024), None);
    }

    #[test]
    fn test_parse_size_not_divisible_by_16() {
        let req = GenerateRequest {
            size: "100x100".into(),
            ..generate_req_default()
        };
        assert_eq!(req.parse_size(1024), None);
    }

    #[test]
    fn test_default_values() {
        let json = r#"{"prompt": "hello world"}"#;
        let req: GenerateRequest = serde_json::from_str(json).unwrap();
        assert_eq!(req.n, 1);
        assert_eq!(req.size, "1024x1024");
        assert_eq!(req.response_format, "b64_json");
    }

    fn generate_req_default() -> GenerateRequest {
        GenerateRequest {
            prompt: String::new(),
            model: None,
            n: 1,
            size: "1024x1024".into(),
            response_format: "b64_json".into(),
            quality: None,
            style: None,
            user: None,
        }
    }
}
