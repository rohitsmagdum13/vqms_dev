"""VQMS - Vendor Query Management System.

Entry point for the FastAPI application.
"""

from fastapi import FastAPI

app = FastAPI(title="VQMS", version="0.1.0")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "phase": 1}
