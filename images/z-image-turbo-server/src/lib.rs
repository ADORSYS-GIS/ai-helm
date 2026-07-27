//! Z-Image-Turbo inference server library.
//!
//! This library exposes the server modules for integration testing.
//! The binary entrypoint is in `main.rs`.

pub mod api;
pub mod config;
pub mod error;
pub mod inference;

// Re-export commonly used types for convenience across modules.
pub use error::ServerError;
