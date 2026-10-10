from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from web.api import router as api_router
from web.storage import init_db

init_db()

app = FastAPI(title="Recap English → Myanmar", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static and uploads
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

uploads_dir = ROOT_DIR / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

app.include_router(api_router)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "recap-en-to-mm", "version": "2.0.0"}


@app.get("/", response_class=HTMLResponse)
def serve_index(request: Request):
    index_file = Path(__file__).parent / "templates" / "index.html"
    if not index_file.is_file():
        return HTMLResponse("<h1>Recap Web App</h1><p>Template loading...</p>")
    return HTMLResponse(index_file.read_text(encoding="utf-8"))
