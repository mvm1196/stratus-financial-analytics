"""
api.py

FastAPI wrapper around the PDF summarizer so stratus-app (and other services)
can request Markdown summaries over HTTP.

Endpoints:
    GET  /health            -> liveness/readiness check
    POST /summarize         -> multipart 'file' (PDF) -> JSON { filename, markdown }

Auth (optional): if SERVICE_TOKEN is set, requests must send
    Authorization: Bearer <SERVICE_TOKEN>

Run locally:
    uvicorn api:app --reload --port 8000
"""

import io
import os

import anthropic
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from summarize_pdf_report import (
    cleanup_file,
    summarize_file_id,
    upload_pdf_fileobj,
)

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 20 * 1024 * 1024))  # 20 MB
SERVICE_TOKEN = os.environ.get("SERVICE_TOKEN", "")
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

app = FastAPI(title="Stratus Financial Analytics", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SummaryResponse(BaseModel):
    filename: str
    markdown: str


def _check_auth(authorization: str | None) -> None:
    if not SERVICE_TOKEN:
        return
    expected = f"Bearer {SERVICE_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured on the service.",
        )
    return anthropic.Anthropic(api_key=api_key)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/summarize", response_model=SummaryResponse)
async def summarize(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> SummaryResponse:
    _check_auth(authorization)

    filename = file.filename or "report.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES} byte limit.",
        )

    client = _client()
    file_id = None
    try:
        file_id = upload_pdf_fileobj(client, filename, io.BytesIO(data))
        markdown = summarize_file_id(client, filename, file_id)
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Anthropic API error: {exc}") from exc
    finally:
        if file_id:
            cleanup_file(client, file_id)

    return SummaryResponse(filename=filename, markdown=markdown)
