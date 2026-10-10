from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import yt_dlp

from web.storage import insert_source, ROOT_DIR, UPLOADS_DIR

THUMB_DIR = ROOT_DIR / "uploads" / "thumbs"
THUMB_DIR.mkdir(parents=True, exist_ok=True)


def _safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")
    return cleaned[:60] or "video"


def probe_video(video_path: Path, ffprobe: str = "ffprobe") -> dict[str, Any]:
    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json",
        str(video_path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout)
        stream = (data.get("streams") or [{}])[0]
        fmt = data.get("format") or {}
        duration = float(stream.get("duration") or fmt.get("duration") or 0.0)
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        return {"duration": duration, "width": width, "height": height}
    except Exception:
        return {"duration": 0.0, "width": 1920, "height": 1080}


def generate_thumbnail(video_path: Path, thumb_path: Path, seek_seconds: float = 1.0, ffmpeg: str = "ffmpeg") -> bool:
    cmd = [
        ffmpeg,
        "-y",
        "-ss", str(max(0.1, seek_seconds)),
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", "scale=480:-1",
        str(thumb_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return thumb_path.is_file()
    except Exception:
        return False


class DownloaderService:
    def __init__(self) -> None:
        self.active_tasks: dict[str, dict[str, Any]] = {}

    def download_url(
        self,
        url: str,
        *,
        progress_cb: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> dict[str, Any]:
        task_id = str(uuid.uuid4())[:8]
        self.active_tasks[task_id] = {
            "status": "downloading",
            "percent": 0.0,
            "speed": "",
            "eta": "",
            "title": "",
        }

        def hook(d: dict[str, Any]) -> None:
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                percent = round(downloaded / total * 100.0, 1) if total > 0 else 0.0
                speed = d.get("_speed_str") or ""
                eta = d.get("_eta_str") or ""
                info = {
                    "status": "downloading",
                    "percent": percent,
                    "speed": speed,
                    "eta": eta,
                }
                self.active_tasks[task_id].update(info)
                if progress_cb:
                    progress_cb(self.active_tasks[task_id])
            elif d.get("status") == "finished":
                self.active_tasks[task_id].update({"status": "processing", "percent": 100.0})
                if progress_cb:
                    progress_cb(self.active_tasks[task_id])

        # yt-dlp options
        unique_prefix = f"ytdl_{int(time.time())}_{task_id}"
        outtmpl = str(UPLOADS_DIR / f"{unique_prefix}_%(title).50s.%(ext)s")

        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "retries": 3,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                title = info_dict.get("title") or "Downloaded Video"
                self.active_tasks[task_id]["title"] = title

                # Determine saved filename
                filename = ydl.prepare_filename(info_dict)
                p = Path(filename)
                if not p.is_file():
                    # Check if merged to .mp4
                    p_mp4 = p.with_suffix(".mp4")
                    if p_mp4.is_file():
                        p = p_mp4
                    else:
                        candidates = list(UPLOADS_DIR.glob(f"{unique_prefix}*"))
                        if candidates:
                            p = candidates[0]
                        else:
                            raise FileNotFoundError("Downloaded video file not found on disk")

                # Probe video
                meta = probe_video(p)
                seek = min(2.0, meta["duration"] / 2.0) if meta["duration"] > 0 else 1.0

                # Thumbnail
                thumb_rel = f"uploads/thumbs/{p.stem}.jpg"
                thumb_path = ROOT_DIR / thumb_rel
                generate_thumbnail(p, thumb_path, seek_seconds=seek)

                # Store record
                source_id = f"src_{task_id}"
                record = insert_source(
                    source_id=source_id,
                    name=title,
                    filename=p.name,
                    source_type="ytdlp",
                    source_url=url,
                    duration=meta["duration"],
                    width=meta["width"],
                    height=meta["height"],
                    file_size=p.stat().st_size,
                    thumbnail_path=thumb_rel if thumb_path.is_file() else "",
                )

                self.active_tasks[task_id]["status"] = "completed"
                self.active_tasks[task_id]["record"] = record
                return record

        except Exception as exc:
            self.active_tasks[task_id]["status"] = "failed"
            self.active_tasks[task_id]["error"] = str(exc)
            raise RuntimeError(f"Download failed: {exc}")
