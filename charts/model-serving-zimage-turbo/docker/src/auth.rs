//! Bearer token authentication — lightweight per-handler check.
//!
//! Instead of a Transform-based middleware (which requires complex body-type
//! gymnastics), this module provides a simple `check_auth` function called
//! directly from route handlers.

use actix_web::HttpRequest;

/// Verify the `Authorization: Bearer <token>` header against the expected key.
///
/// Returns `true` if the request is authenticated or if no key is configured.
pub fn check_auth(req: &HttpRequest, expected_key: Option<&str>) -> bool {
    let Some(expected) = expected_key else {
        // No API key configured → auth disabled.
        return true;
    };

    let header = req
        .headers()
        .get("Authorization")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.trim());

    match header {
        Some(h) if h.len() > 7 && h[..7].eq_ignore_ascii_case("Bearer ") => {
            h[7..].trim() == expected
        }
        _ => false,
    }
}

/// Build a 401 Unauthorized JSON response.
pub fn unauthorized_response() -> actix_web::HttpResponse {
    actix_web::HttpResponse::Unauthorized()
        .insert_header(("WWW-Authenticate", "Bearer"))
        .json(serde_json::json!({
            "error": {
                "code": "unauthorized",
                "message": "Invalid or missing API key. Provide it as: Authorization: Bearer <key>",
                "type": "auth_error"
            }
        }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::test;

    #[actix_web::test]
    async fn test_check_valid_token() {
        let req = test::TestRequest::get()
            .insert_header(("Authorization", "Bearer test-key"))
            .to_http_request();
        assert!(check_auth(&req, Some("test-key")));
    }

    #[actix_web::test]
    async fn test_check_invalid_token() {
        let req = test::TestRequest::get()
            .insert_header(("Authorization", "Bearer wrong-key"))
            .to_http_request();
        assert!(!check_auth(&req, Some("test-key")));
    }

    #[actix_web::test]
    async fn test_check_missing_header() {
        let req = test::TestRequest::get().to_http_request();
        assert!(!check_auth(&req, Some("test-key")));
    }

    #[actix_web::test]
    async fn test_check_no_auth_configured() {
        let req = test::TestRequest::get().to_http_request();
        assert!(check_auth(&req, None));
    }

    #[actix_web::test]
    async fn test_check_case_insensitive_bearer() {
        let req = test::TestRequest::get()
            .insert_header(("Authorization", "bearer test-key"))
            .to_http_request();
        assert!(check_auth(&req, Some("test-key")));
    }

    #[actix_web::test]
    async fn test_check_trims_whitespace() {
        let req = test::TestRequest::get()
            .insert_header(("Authorization", "Bearer   test-key   "))
            .to_http_request();
        assert!(check_auth(&req, Some("test-key")));
    }
}
