# syntax=docker/dockerfile:1
# Z-Image-Turbo server — Rust + Candle + CUDA
#
# First-party inference server for Tongyi-MAI/Z-Image-Turbo, exposing the
# OpenAI-compatible POST /v1/images/generations. Consumed by the `zimage` engine
# profile in charts/model-serving (ADR-0100); the chart references the published
# tag, it does NOT build this.
#
# Build (from this directory):
#   docker build -t ghcr.io/adorsys-gis/z-image-turbo-server:v0.2.0 .
#   docker push  ghcr.io/adorsys-gis/z-image-turbo-server:v0.2.0
#
# Run:
#   docker run --gpus all -p 8080:8080 \
#     -e MODEL_DIR=/models/Z-Image-Turbo -v /path/to/weights:/models:ro \
#     ghcr.io/adorsys-gis/z-image-turbo-server:v0.2.0 --port 8080
#
# ⚠️ TWO THINGS THIS IMAGE MUST MATCH, AND BOTH BITE SILENTLY IF WRONG
#
#   1. CUDA_COMPUTE_CAP. Candle compiles its CUDA kernels for ONE compute
#      capability at build time, defaulting to whatever card the BUILD machine
#      has. The Hetzner GPU fleet runs RTX 4000 SFF Ada = sm_89. An image built
#      on the old home RTX A2000 (sm_86) produces cubins the Ada cards cannot
#      load, and the failure surfaces at first inference — long after the pod
#      went Ready — as a CUDA "no kernel image is available for execution on the
#      device" error. Pinned below; change it when the fleet hardware changes.
#
#   2. CUDA MAJOR/MINOR vs the node driver. The fleet nodes run driver
#      550.163.01 / CUDA 12.4. This is the same trap CLAUDE.md records for
#      llama.cpp's `server-cuda13` tag and vLLM's `-cu129` tag: a newer CUDA
#      base than the driver supports fails at start-up. Build against 12.4.
#
# Why Rust rather than Python/diffusers: ~150 MB binary vs a ~3 GB torch image,
# sub-second process start, and no GIL around a single-GPU model guarded by a
# Mutex. The trade is that Candle's `z_image` module — not diffusers — is the
# reference implementation we depend on (candle-transformers 0.11).

# ── Builder stage ──────────────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS builder

LABEL stage=builder

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libssl-dev \
        libclang-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Rust via rustup. `edition = "2024"` in Cargo.toml needs Rust >= 1.85, so the
# toolchain is deliberately `stable` rather than a pin that could age below it.
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --profile minimal --default-toolchain stable

WORKDIR /build

# Target the fleet's GPUs. See the header — this is read by candle's build
# script, and it is NOT related to Rust's `target-cpu` (which is host CPU only).
# Set before the dependency build so the cached layer holds the right kernels.
ENV CUDA_COMPUTE_CAP=89

# `-fuse-ld=lld` is deliberately NOT set: lld is not installed in this image and
# passing it fails the link with a bare "cannot find -fuse-ld=lld".
ENV CARGO_PROFILE_RELEASE_LTO=fat \
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
    CARGO_PROFILE_RELEASE_OPT_LEVEL=3 \
    CARGO_PROFILE_RELEASE_PANIC=abort \
    RUSTFLAGS="-C target-cpu=x86-64-v3"

# Manifests first, so the (very slow) dependency build layer caches across
# source edits. The dummy main.rs exists only to give cargo something to
# compile; it is removed before the real sources land.
COPY Cargo.toml Cargo.lock ./
RUN mkdir -p src && \
    echo "fn main() {}" > src/main.rs && \
    cargo build --release --features cuda ; \
    rm -rf src

COPY src/ src/

RUN cargo build --release --features cuda --bin zimage-turbo-server && \
    strip /build/target/release/zimage-turbo-server

# Unit tests live inline (`#[cfg(test)] mod tests`) in the source files — there
# is no tests/ directory, and adding a COPY for one breaks the build. Compiled
# but not run: they need no GPU, the build host may not have one.
RUN cargo test --release --features cuda --no-run

# ── Runtime stage ──────────────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04 AS runtime

LABEL org.opencontainers.image.source="https://github.com/ADORSYS-GIS/ai-helm"
LABEL org.opencontainers.image.description="Z-Image-Turbo inference server (Rust/Candle, OpenAI /v1/images/generations)"
LABEL org.opencontainers.image.licenses="Apache-2.0"

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Non-root by construction. The chart runs this as 1002 with a read-only root
# filesystem — the process writes nothing outside the weights mount, which is
# itself mounted read-only.
RUN groupadd -r zimage --gid 1002 && useradd -r -g zimage -m -d /app zimage --uid 1002

WORKDIR /app

COPY --from=builder /build/target/release/zimage-turbo-server /app/zimage-turbo-server

# Cheap proof the binary links against the runtime image's CUDA libraries.
RUN /app/zimage-turbo-server --help

# Kubernetes uses the chart's probes, not this; kept for `docker run` parity.
# The model is pre-loaded at start-up (see src/main.rs), so /health answers 503
# until the weights are on the GPU and 200 after — which is what the chart's
# startup probe gates on.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

USER zimage

ENTRYPOINT ["/app/zimage-turbo-server"]
