from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .docling_service import PIPELINE_METADATA, convert_pdf

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", BASE_DIR / "data" / "documents")).resolve()
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Docling Heron + EasyOCR Layout Viewer")


def _ensure_pdf(upload: UploadFile) -> str:
    filename = upload.filename or "document.pdf"
    suffix = Path(filename).suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")
    return filename


@app.get("/api/health")
def healthcheck() -> dict[str, object]:
    return {"status": "ok", **PIPELINE_METADATA}


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)) -> dict[str, object]:
    filename = _ensure_pdf(file)

    document_id = uuid4().hex
    document_dir = DOCUMENTS_DIR / document_id
    document_dir.mkdir(parents=True, exist_ok=True)
    source_path = document_dir / "source.pdf"

    payload = await file.read()
    source_path.write_bytes(payload)

    analysis = convert_pdf(source_path)
    return {
        "documentId": document_id,
        "filename": filename,
        "pdfUrl": f"/api/documents/{document_id}/file",
        **analysis,
    }


@app.get("/api/documents/{document_id}/file")
def get_document_file(document_id: str) -> FileResponse:
    source_path = DOCUMENTS_DIR / document_id / "source.pdf"
    if not source_path.exists():
        raise HTTPException(status_code=404, detail="Document not found.")

    return FileResponse(source_path, media_type="application/pdf", filename=source_path.name)


if FRONTEND_DIST_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST_DIR / "assets"),
        name="frontend-assets",
    )

    @app.get("/", response_class=HTMLResponse)
    def serve_index() -> HTMLResponse:
        return HTMLResponse((FRONTEND_DIST_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    def serve_spa(full_path: str) -> HTMLResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        return HTMLResponse((FRONTEND_DIST_DIR / "index.html").read_text(encoding="utf-8"))
