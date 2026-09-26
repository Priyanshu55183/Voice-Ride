"""FastAPI application entrypoint (Phase 2+ — REST API for dashboard and integrations)."""

from fastapi import FastAPI

app = FastAPI(
    title="VoiceRide",
    description="Personal voice assistant for parallel multi-app cab booking",
    version="0.1.0",
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}
