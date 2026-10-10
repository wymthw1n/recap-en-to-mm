from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "app.db"
UPLOADS_DIR = ROOT_DIR / "uploads"
JOBS_DIR = ROOT_DIR / "jobs"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
JOBS_DIR.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            filename TEXT NOT NULL,
            source_type TEXT NOT NULL, -- 'upload' | 'ytdlp'
            source_url TEXT DEFAULT '',
            duration REAL DEFAULT 0.0,
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            file_size INTEGER DEFAULT 0,
            thumbnail_path TEXT DEFAULT '',
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            source_title TEXT NOT NULL,
            source_path TEXT NOT NULL,
            status TEXT NOT NULL, -- 'pending', 'running', 'completed', 'failed', 'stopped'
            stage TEXT DEFAULT 'Idle',
            progress_current INTEGER DEFAULT 0,
            progress_total INTEGER DEFAULT 0,
            progress_label TEXT DEFAULT '',
            voice TEXT DEFAULT 'my-MM-ThihaNeural',
            output_ratio TEXT DEFAULT '16:9',
            output_video_path TEXT DEFAULT '',
            job_dir TEXT NOT NULL,
            settings_json TEXT DEFAULT '{}',
            error_message TEXT DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources (id) ON DELETE SET NULL
        );
        """)
    conn.close()


init_db()


# Sources operations
def insert_source(
    *,
    source_id: str,
    name: str,
    filename: str,
    source_type: str,
    source_url: str = "",
    duration: float = 0.0,
    width: int = 0,
    height: int = 0,
    file_size: int = 0,
    thumbnail_path: str = "",
) -> dict[str, Any]:
    now = time.time()
    conn = get_db()
    with conn:
        conn.execute(
            """
            INSERT INTO sources (id, name, filename, source_type, source_url, duration, width, height, file_size, thumbnail_path, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (source_id, name, filename, source_type, source_url, duration, width, height, file_size, thumbnail_path, now),
        )
    conn.close()
    return get_source(source_id) or {}


def get_source(source_id: str) -> Optional[dict[str, Any]]:
    conn = get_db()
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_sources() -> list[dict[str, Any]]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_source(source_id: str) -> bool:
    src = get_source(source_id)
    if not src:
        return False
    # Remove files
    file_path = UPLOADS_DIR / src["filename"]
    if file_path.is_file():
        try:
            file_path.unlink()
        except OSError:
            pass
    if src.get("thumbnail_path"):
        thumb = ROOT_DIR / src["thumbnail_path"]
        if thumb.is_file():
            try:
                thumb.unlink()
            except OSError:
                pass
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.close()
    return True


# Jobs operations
def insert_or_update_job(
    *,
    job_id: str,
    source_id: str,
    source_title: str,
    source_path: str,
    status: str,
    stage: str = "Idle",
    progress_current: int = 0,
    progress_total: int = 0,
    progress_label: str = "",
    voice: str = "my-MM-ThihaNeural",
    output_ratio: str = "16:9",
    output_video_path: str = "",
    job_dir: str = "",
    settings_json: str = "{}",
    error_message: str = "",
) -> dict[str, Any]:
    now = time.time()
    conn = get_db()
    with conn:
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, source_id, source_title, source_path, status, stage,
                progress_current, progress_total, progress_label, voice,
                output_ratio, output_video_path, job_dir, settings_json,
                error_message, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status = excluded.status,
                stage = excluded.stage,
                progress_current = excluded.progress_current,
                progress_total = excluded.progress_total,
                progress_label = excluded.progress_label,
                voice = excluded.voice,
                output_ratio = excluded.output_ratio,
                output_video_path = CASE WHEN excluded.output_video_path != '' THEN excluded.output_video_path ELSE jobs.output_video_path END,
                settings_json = excluded.settings_json,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            """,
            (
                job_id, source_id, source_title, source_path, status, stage,
                progress_current, progress_total, progress_label, voice,
                output_ratio, output_video_path, job_dir, settings_json,
                error_message, now, now
            ),
        )
    conn.close()
    return get_job(job_id) or {}


def update_job_progress(
    job_id: str,
    *,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    current: Optional[int] = None,
    total: Optional[int] = None,
    label: Optional[str] = None,
    output_video_path: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    now = time.time()
    updates = ["updated_at = ?"]
    params: list[Any] = [now]
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if stage is not None:
        updates.append("stage = ?")
        params.append(stage)
    if current is not None:
        updates.append("progress_current = ?")
        params.append(current)
    if total is not None:
        updates.append("progress_total = ?")
        params.append(total)
    if label is not None:
        updates.append("progress_label = ?")
        params.append(label)
    if output_video_path is not None:
        updates.append("output_video_path = ?")
        params.append(output_video_path)
    if error_message is not None:
        updates.append("error_message = ?")
        params.append(error_message)

    params.append(job_id)
    conn = get_db()
    with conn:
        conn.execute(f"UPDATE jobs SET {', '.join(updates)} WHERE job_id = ?", params)
    conn.close()


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_jobs() -> list[dict[str, Any]]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_job(job_id: str) -> bool:
    job = get_job(job_id)
    if not job:
        return False
    jdir = Path(job["job_dir"])
    if jdir.is_dir():
        import shutil
        shutil.rmtree(jdir, ignore_errors=True)
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
    conn.close()
    return True
