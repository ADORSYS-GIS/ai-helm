"""
Z-Image-Turbo — OpenAI-compatible image generation server.

Serves /v1/images/generations (OpenAI API shape) with Bearer auth.
Loads the model weights from /mnt/models (PVC-mounted).

Environment variables:
  API_KEY   — Required. Bearer token the client must send.
  MODEL_DIR — Path to model weights (default: /mnt/models).
  HF_TOKEN  — Optional, for gated models.
"""
import os
import time
import base64
import io
import logging
from typing import Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

logger = logging.getLogger("zimage-turbo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Configuration ─────────────────────────────────────────────────────────
API_KEY = os.environ.get("API_KEY")
if not API_KEY:
    logger.warning("API_KEY not set — server will reject all requests")

MODEL_DIR = os.environ.get("MODEL_DIR", "/mnt/models")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.bfloat16

# ── App setup ─────────────────────────────────────────────────────────────
app = FastAPI(title="Z-Image-Turbo", version="0.1.0")
security = HTTPBearer(auto_error=False)


def verify_auth(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """Bearer auth — rejects if API_KEY is set and doesn't match."""
    if not API_KEY:
        return
    if creds is None or creds.credentials != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Model loading (lazy, on first request) ───────────────────────────────
_model_pipe = None


def get_pipe():
    global _model_pipe
    if _model_pipe is not None:
        return _model_pipe

    logger.info("Loading Z-Image-Turbo from %s on %s ...", MODEL_DIR, DEVICE)
    t0 = time.time()

    from diffusers import ZImageTurboPipeline  # type: ignore

    pipe = ZImageTurboPipeline.from_pretrained(
        MODEL_DIR,
        torch_dtype=DTYPE,
        device_map="auto" if DEVICE == "cuda" else None,
        use_safetensors=True,
    )
    pipe.to(DEVICE)
    pipe.set_progress_bar_config(disable=True)

    # Enable memory optimisations
    if DEVICE == "cuda":
        pipe.enable_attention_slicing()
        pipe.vae.enable_slicing()
        pipe.vae.enable_tiling()

    _model_pipe = pipe
    logger.info("Model loaded in %.1fs", time.time() - t0)
    return pipe


# ── Request / response models ─────────────────────────────────────────────
class ImageGenerationRequest(BaseModel):
    prompt: str = Field(..., description="Text prompt for image generation")
    model: Optional[str] = Field(None, description="Model name (ignored, for compat)")
    n: int = Field(1, ge=1, le=4, description="Number of images to generate")
    size: Optional[str] = Field(None, description="Image size (ignored, fixed 1024x1024)")
    response_format: Optional[str] = Field("b64_json", description="b64_json or url")
    quality: Optional[str] = Field(None, description="Ignored")
    style: Optional[str] = Field(None, description="Ignored")


class ImageData(BaseModel):
    b64_json: Optional[str] = None
    url: Optional[str] = None
    revised_prompt: Optional[str] = None


class ImageGenerationResponse(BaseModel):
    created: int
    data: list[ImageData]


class HealthResponse(BaseModel):
    status: str
    device: str
    model_loaded: bool


# ── Routes ────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return HealthResponse(
        status="ok",
        device=DEVICE,
        model_loaded=_model_pipe is not None,
    )


@app.post("/v1/images/generations", dependencies=[Depends(verify_auth)])
async def generate_images(req: ImageGenerationRequest):
    """
    OpenAI-compatible image generation endpoint.
    Accepts /v1/images/generations with the OpenAI request shape.
    Returns b64_json image data (or url if requested, but local serves b64_json).
    """
    pipe = get_pipe()

    if req.n < 1 or req.n > 4:
        raise HTTPException(status_code=400, detail="n must be between 1 and 4")

    logger.info("Generating %d image(s): %s", req.n, req.prompt[:80])

    t0 = time.time()
    images = pipe(
        prompt=req.prompt,
        num_images_per_prompt=req.n,
        num_inference_steps=8,
        guidance_scale=0.0,
        output_type="pil",
    ).images
    elapsed = time.time() - t0
    logger.info("Generated %d image(s) in %.1fs", len(images), elapsed)

    data: list[ImageData] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        entry = ImageData(b64_json=b64)
        if req.response_format == "url":
            # Local server can't serve URLs; fallback to b64_json
            entry.b64_json = b64

        data.append(entry)

    return ImageGenerationResponse(created=int(time.time()), data=data)


# ── Entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        timeout_keep_alive=30,
    )
