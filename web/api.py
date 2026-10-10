from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app.preview_tools import extract_preview_frame, probe_duration
from web.downloader import DownloaderService, generate_thumbnail, probe_video
from web.job_runner import job_runner
from web.settings_service import get_settings, test_gemini_key, update_settings
from web.storage import (
    JOBS_DIR,
    ROOT_DIR,
    UPLOADS_DIR,
    delete_job,
    delete_source,
    get_job,
    get_source,
    insert_or_update_job,
    insert_source,
    list_jobs,
    list_sources,
)

router = APIRouter(prefix="/api")
downloader = DownloaderService()

LOGOS_DIR = UPLOADS_DIR / "logos"
PREVIEWS_DIR = ROOT_DIR / "logs" / "previews"
LOGOS_DIR.mkdir(parents=True, exist_ok=True)
PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(text: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")
    return cleaned[:80] or "recap_video"


def _job_dir_for(source_path: Path) -> Path:
    raw = str(source_path.resolve()).encode("utf-8")
    sig = hashlib.sha1(raw).hexdigest()[:8]
    return JOBS_DIR / f"{_safe_name(source_path.stem)}_{sig}"


# ---------------- Sources / Uploads ----------------

@router.get("/sources")
def api_list_sources() -> list[dict[str, Any]]:
    return list_sources()


@router.delete("/sources/{source_id}")
def api_delete_source(source_id: str) -> dict[str, Any]:
    ok = delete_source(source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"ok": True}


@router.post("/upload/video")
async def api_upload_video(file: UploadFile = File(...)) -> dict[str, Any]:
    ext = Path(file.filename or "video.mp4").suffix.lower()
    if ext not in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}:
        ext = ".mp4"

    source_id = f"src_{uuid.uuid4().hex[:8]}"
    clean_stem = _safe_name(Path(file.filename or "uploaded").stem)
    save_filename = f"{clean_stem}_{source_id}{ext}"
    target_path = UPLOADS_DIR / save_filename

    # Stream write
    with target_path.open("wb") as out_f:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            out_f.write(chunk)

    # Probe
    meta = probe_video(target_path)
    seek = min(2.0, meta["duration"] / 2.0) if meta["duration"] > 0 else 1.0

    # Thumbnail
    thumb_rel = f"uploads/thumbs/{target_path.stem}.jpg"
    thumb_path = ROOT_DIR / thumb_rel
    generate_thumbnail(target_path, thumb_path, seek_seconds=seek)

    record = insert_source(
        source_id=source_id,
        name=Path(file.filename or clean_stem).stem,
        filename=save_filename,
        source_type="upload",
        source_url="",
        duration=meta["duration"],
        width=meta["width"],
        height=meta["height"],
        file_size=target_path.stat().st_size,
        thumbnail_path=thumb_rel if thumb_path.is_file() else "",
    )
    return record


@router.post("/upload/logo")
async def api_upload_logo(file: UploadFile = File(...)) -> dict[str, Any]:
    ext = Path(file.filename or "logo.png").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"
    save_filename = f"logo_{uuid.uuid4().hex[:8]}{ext}"
    target_path = LOGOS_DIR / save_filename
    with target_path.open("wb") as out_f:
        while chunk := await file.read(512 * 1024):
            out_f.write(chunk)

    rel_path = f"uploads/logos/{save_filename}"
    return {"path": str(target_path), "rel_path": rel_path, "filename": save_filename}


class DownloadRequest(BaseModel):
    url: str


@router.post("/download")
async def api_download_url(req: DownloadRequest) -> dict[str, Any]:
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    try:
        # Run blocking yt-dlp in threadpool
        loop = asyncio.get_event_loop()
        record = await loop.run_in_executor(None, lambda: downloader.download_url(url))
        return record
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------- Jobs ----------------

class CreateJobRequest(BaseModel):
    source_id: str
    voice: Optional[str] = "my-MM-ThihaNeural"
    edge_tts_rate: Optional[str] = "+0%"
    edge_tts_pitch: Optional[str] = "+0Hz"
    output_ratio: Optional[str] = "16:9"
    frame_fill: Optional[str] = "blur"
    zoom_factor: Optional[float] = 1.05
    mirror_video: Optional[bool] = False
    voice_volume_percent: Optional[int] = 100
    short_pauses: Optional[bool] = True
    reuse_plan: Optional[bool] = True
    max_video_speed: Optional[float] = 1.25
    max_video_slow: Optional[float] = 1.35
    enable_original_background: Optional[bool] = False
    original_background_volume: Optional[int] = 25
    overlays: Optional[dict[str, Any]] = None


@router.get("/jobs")
def api_list_jobs() -> list[dict[str, Any]]:
    return list_jobs()


@router.get("/jobs/{job_id}")
def api_get_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs")
def api_create_job(req: CreateJobRequest) -> dict[str, Any]:
    src = get_source(req.source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source video not found")

    source_path = UPLOADS_DIR / src["filename"]
    if not source_path.is_file():
        raise HTTPException(status_code=400, detail="Source file missing from disk")

    job_dir = _job_dir_for(source_path)
    job_id = job_dir.name

    overlays = req.overlays or {
        "blur_boxes": [],
        "blur_strength": 18,
        "title_text": "",
        "title_position": [0.50, 0.12],
        "title_font_size": 54,
        "title_font_path": "",
        "logo_enabled": False,
        "logo_path": "",
        "logo_position": [0.80, 0.06],
        "logo_width_fraction": 0.16,
        "logo_opacity": 0.65,
        "extra_text": "",
        "extra_text_position": [0.50, 0.84],
        "extra_text_font_size": 42,
        "extra_text_opacity": 0.65,
        "burn_subtitles": True,
        "subtitle_size_percent": 3.6,
        "subtitle_box_width_percent": 85.0,
        "subtitle_font_size": 3.6,
        "subtitle_font_color": "#FFDE00",
        "subtitle_position": [0.50, 0.86],
        "subtitle_style": "outline",
    }

    settings = {
        "edge_tts_rate": req.edge_tts_rate or "+0%",
        "edge_tts_pitch": req.edge_tts_pitch or "+0Hz",
        "output_ratio": req.output_ratio or "16:9",
        "frame_fill": req.frame_fill or "blur",
        "zoom_factor": req.zoom_factor or 1.05,
        "mirror_video": bool(req.mirror_video),
        "voice_volume_percent": req.voice_volume_percent or 100,
        "short_pauses": bool(req.short_pauses),
        "reuse_plan": bool(req.reuse_plan),
        "max_video_speed": req.max_video_speed or 1.25,
        "max_video_slow": req.max_video_slow or 1.35,
        "enable_original_background": bool(req.enable_original_background),
        "original_background_volume": int(req.original_background_volume if req.original_background_volume is not None else 25),
        "overlays": overlays,
    }

    record = insert_or_update_job(
        job_id=job_id,
        source_id=req.source_id,
        source_title=src["name"],
        source_path=str(source_path),
        status="pending",
        stage="Queued",
        voice=req.voice or "my-MM-ThihaNeural",
        output_ratio=req.output_ratio or "16:9",
        job_dir=str(job_dir),
        settings_json=json.dumps(settings, ensure_ascii=False),
    )

    # Launch in background
    job_runner.start_job(job_id)
    return record


@router.post("/jobs/{job_id}/stop")
def api_stop_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job_runner.stop_job(job_id)
    return {"ok": True}


@router.post("/jobs/{job_id}/resume")
def api_resume_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    # Resume with reuse
    settings = json.loads(job["settings_json"] or "{}")
    settings["reuse_plan"] = True
    insert_or_update_job(
        job_id=job_id,
        source_id=job["source_id"],
        source_title=job["source_title"],
        source_path=job["source_path"],
        status="pending",
        stage="Resuming",
        voice=job["voice"],
        output_ratio=job["output_ratio"],
        job_dir=job["job_dir"],
        settings_json=json.dumps(settings, ensure_ascii=False),
    )
    job_runner.start_job(job_id)
    return {"ok": True}


@router.delete("/jobs/{job_id}")
def api_delete_job(job_id: str) -> dict[str, Any]:
    ok = delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True}


@router.get("/jobs/{job_id}/final")
def api_get_final_video(job_id: str):
    job = get_job(job_id)
    if not job or not job.get("output_video_path"):
        raise HTTPException(status_code=404, detail="Final video not found")
    video_path = Path(job["output_video_path"])
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Final video file not found on disk")
    return FileResponse(
        str(video_path),
        media_type="video/mp4",
        filename=f"{_safe_name(job['source_title'])}_myanmar.mp4",
    )


@router.get("/jobs/{job_id}/logs")
def api_get_job_logs(job_id: str, tail: int = 150) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    log_file = Path(job["job_dir"]) / "run.log"
    if not log_file.is_file():
        return {"logs": ""}
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"logs": "\n".join(lines[-tail:])}
    except Exception as exc:
        return {"logs": f"Error reading logs: {exc}"}


@router.get("/jobs/{job_id}/plan")
def api_get_job_plan(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    jdir = Path(job["job_dir"])
    plan_path = jdir / "smart_sync_plan.json"
    trans_path = jdir / "timestamp_translations.json"
    transcript_path = jdir / "whisper_transcript.txt"

    data: dict[str, Any] = {}
    if plan_path.is_file():
        try:
            data["plan"] = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if trans_path.is_file():
        try:
            data["translations"] = json.loads(trans_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    if transcript_path.is_file():
        try:
            data["whisper_transcript"] = transcript_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return data


# ---------------- Preview Frame ----------------

@router.get("/preview/frame")
def api_get_preview_frame(
    source_id: str,
    time: float = 1.0,
    zoom: float = 1.05,
    mirror: bool = False,
    ratio: str = "16:9",
    fill: str = "blur",
    w: Optional[int] = None,
    h: Optional[int] = None,
):
    src = get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    source_path = UPLOADS_DIR / src["filename"]
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail="Source file not found")

    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    sw = int(src.get("width") or 0)
    sh = int(src.get("height") or 0)

    try:
        from core import output_canvas, _even
    except ImportError:
        from app.core import output_canvas, _even

    cw, ch = output_canvas(ratio, sw, sh)
    if w and h:
        pw, ph = int(w), int(h)
    else:
        scale = min(640.0 / max(cw, 1), 640.0 / max(ch, 1))
        pw = max(2, _even(cw * scale))
        ph = max(2, _even(ch * scale))

    safe_ratio = ratio.replace(":", "x")
    out_file = PREVIEWS_DIR / f"prev_{source_id}_{int(time*100)}_{safe_ratio}_{fill}_{int(zoom*100)}_{pw}x{ph}_{1 if mirror else 0}.jpg"

    try:
        extract_preview_frame(
            ffmpeg=ffmpeg,
            source=str(source_path),
            timestamp=max(0.0, time),
            zoom=float(zoom),
            mirror=bool(mirror),
            output=str(out_file),
            width=pw,
            height=ph,
            ratio=ratio,
            fill=fill,
            source_size=(sw, sh),
        )
        return FileResponse(str(out_file), media_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {exc}")


# ---------------- Settings ----------------

@router.get("/settings")
def api_get_settings() -> dict[str, Any]:
    return get_settings()


@router.post("/settings")
def api_update_settings(data: dict[str, Any]) -> dict[str, Any]:
    return update_settings(data)


class TestKeyRequest(BaseModel):
    api_key: str
    proxy: Optional[str] = ""


@router.post("/settings/test-key")
def api_test_key(req: TestKeyRequest) -> dict[str, Any]:
    return test_gemini_key(req.api_key, proxy=req.proxy or "")


# ---------------- Subtitle Downloads ----------------

@router.get("/jobs/{job_id}/subtitles.srt")
def api_download_subtitles_srt(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    srt_path = Path(job["job_dir"]) / "subtitles.srt"
    if not srt_path.is_file():
        raise HTTPException(status_code=404, detail="Subtitles not generated yet")
    return FileResponse(srt_path, media_type="text/plain", filename=f"{_safe_name(job['source_title'])}_subtitles.srt")


@router.get("/jobs/{job_id}/subtitles.ass")
def api_download_subtitles_ass(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    ass_path = Path(job["job_dir"]) / "subtitles.ass"
    if not ass_path.is_file():
        raise HTTPException(status_code=404, detail="Subtitles not generated yet")
    return FileResponse(ass_path, media_type="text/plain", filename=f"{_safe_name(job['source_title'])}_subtitles.ass")


# ---------------- WebSockets ----------------

@router.websocket("/ws/jobs/{job_id}")
async def websocket_job_logs(websocket: WebSocket, job_id: str):
    await websocket.accept()
    loop = asyncio.get_event_loop()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def listener(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    job_runner.subscribe(job_id, listener)
    try:
        # Send initial job status
        job = get_job(job_id)
        if job:
            await websocket.send_json({
                "kind": "status",
                "status": job["status"],
                "stage": job["stage"],
                "current": job["progress_current"],
                "total": job["progress_total"],
                "label": job["progress_label"],
            })

        while True:
            ev = await queue.get()
            await websocket.send_json(ev)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        job_runner.unsubscribe(job_id, listener)
