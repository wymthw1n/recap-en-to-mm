from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from web.storage import (
    ROOT_DIR,
    JOBS_DIR,
    get_job,
    insert_or_update_job,
    update_job_progress,
)

EVENT_PREFIX = "@@VRS_EVENT@@"


class JobRunner:
    def __init__(self) -> None:
        self.active_processes: dict[str, subprocess.Popen] = {}
        self.active_threads: dict[str, threading.Thread] = {}
        self.stop_events: dict[str, threading.Event] = {}
        self.log_subscribers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._lock = threading.Lock()

    def subscribe(self, job_id: str, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self.log_subscribers.setdefault(job_id, []).append(callback)

    def unsubscribe(self, job_id: str, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if job_id in self.log_subscribers:
                try:
                    self.log_subscribers[job_id].remove(callback)
                except ValueError:
                    pass

    def _broadcast(self, job_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self.log_subscribers.get(job_id, []))
        for cb in subs:
            try:
                cb(event)
            except Exception:
                pass

    def stop_job(self, job_id: str) -> bool:
        with self._lock:
            ev = self.stop_events.get(job_id)
            if ev:
                ev.set()
            job = get_job(job_id)
            if job:
                stop_file = Path(job["job_dir"]) / ".stop_requested"
                try:
                    stop_file.touch()
                except OSError:
                    pass
            proc = self.active_processes.get(job_id)
            if proc:
                try:
                    proc.terminate()
                except OSError:
                    pass
        update_job_progress(job_id, status="stopped", stage="Stopped safely")
        self._broadcast(job_id, {"kind": "stopped", "message": "Job stopped by user"})
        return True

    def start_job(self, job_id: str) -> None:
        job = get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        with self._lock:
            th = self.active_threads.get(job_id)
            if th and th.is_alive():
                return
            stop_ev = threading.Event()
            self.stop_events[job_id] = stop_ev
            thread = threading.Thread(target=self._run_job_thread, args=(job_id, stop_ev), daemon=True)
            self.active_threads[job_id] = thread
            thread.start()

    def _run_child(
        self,
        job_id: str,
        script_name: str,
        cfg_path: Path,
        stage_name: str,
        run_log: Path,
    ) -> dict[str, Any]:
        update_job_progress(job_id, stage=stage_name)
        self._broadcast(job_id, {"kind": "stage", "stage": stage_name})

        def append_log(line: str) -> None:
            try:
                with run_log.open("a", encoding="utf-8", errors="replace") as f:
                    f.write(line + "\n")
            except Exception:
                pass

        append_log(f"\n{'=' * 64}\n{stage_name}\n{'=' * 64}")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        py_exe = sys.executable

        cmd = [py_exe, "-u", str(ROOT_DIR / "app" / script_name), str(cfg_path)]
        append_log("▶ " + " ".join(f'"{x}"' if " " in x else x for x in cmd))

        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )

        with self._lock:
            self.active_processes[job_id] = proc

        result: dict[str, Any] = {}
        reported_error = ""
        stopped_msg = ""

        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if not line:
                    continue

                if line.startswith(EVENT_PREFIX):
                    try:
                        event = json.loads(line[len(EVENT_PREFIX):])
                    except Exception:
                        append_log(line)
                        continue

                    kind = event.get("kind")
                    if kind == "log":
                        text = str(event.get("text", ""))
                        append_log(text)
                        self._broadcast(job_id, {"kind": "log", "text": text})
                    elif kind == "progress":
                        curr = int(event.get("current", 0))
                        total = int(event.get("total", 0))
                        lbl = str(event.get("label", stage_name))
                        update_job_progress(job_id, current=curr, total=total, label=lbl)
                        self._broadcast(job_id, {"kind": "progress", "current": curr, "total": total, "label": lbl})
                    elif kind == "result":
                        result = event
                    elif kind == "error":
                        reported_error = str(event.get("message", ""))
                    elif kind == "stopped":
                        stopped_msg = str(event.get("message", "Stopped"))
                    continue

                append_log(line)
                self._broadcast(job_id, {"kind": "log", "text": line})

            code = proc.wait()
        finally:
            with self._lock:
                if self.active_processes.get(job_id) is proc:
                    self.active_processes.pop(job_id, None)

        if code == 10 or stopped_msg:
            raise InterruptedError(stopped_msg or "Stopped safely")
        if code != 0:
            if reported_error:
                raise RuntimeError(f"{reported_error} (Exit code: {code})")
            raise RuntimeError(f"Child process exited with code {code}. Check run.log")

        return result

    def _run_job_thread(self, job_id: str, stop_ev: threading.Event) -> None:
        job = get_job(job_id)
        if not job:
            return

        job_dir = Path(job["job_dir"])
        job_dir.mkdir(parents=True, exist_ok=True)
        run_log = job_dir / "run.log"

        stop_file = job_dir / ".stop_requested"
        if not stop_ev.is_set():
            stop_file.unlink(missing_ok=True)

        start_time = time.time()
        update_job_progress(job_id, status="running", stage="Starting", error_message="")
        self._broadcast(job_id, {"kind": "status", "status": "running"})

        settings = json.loads(job["settings_json"] or "{}")
        source_path = Path(job["source_path"])
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        ffprobe = shutil.which("ffprobe") or "ffprobe"

        try:
            # STEP 1: Planner
            planner_cfg = job_dir / "_planner_worker.json"
            planner_data = {
                "source_path": str(source_path),
                "source_title": job["source_title"],
                "job_dir": str(job_dir),
                "runtime_root": str(ROOT_DIR / "recap_runtime"),
                "gemini_env_path": str(ROOT_DIR / ".env"),
                "ffprobe_path": ffprobe,
                "reuse": bool(settings.get("reuse_plan", True)),
                "stop_file": str(stop_file),
                "translation_batch_max_items": int(settings.get("translation_batch_max_items", 40)),
                "story_context_batch_max_items": int(settings.get("story_context_batch_max_items", 80)),
                "context_overlap": int(settings.get("context_overlap", 6)),
                "lookahead": int(settings.get("lookahead", 6)),
                "translation_audit": bool(settings.get("translation_audit", True)),
                "atomic_max_duration": float(settings.get("atomic_max_duration", 5.6)),
                "atomic_target_duration": float(settings.get("atomic_target_duration", 4.2)),
                "gemini_request_timeout_seconds": int(settings.get("gemini_request_timeout_seconds", 120)),
                "gemini_text_model": str(settings.get("gemini_text_model", "gemini-3.5-flash")),
            }
            planner_cfg.write_text(json.dumps(planner_data, ensure_ascii=False, indent=2), encoding="utf-8")

            planner_result = self._run_child(
                job_id,
                "planner_worker.py",
                planner_cfg,
                "STEP 1 — Transcript + Context + Translation",
                run_log,
            )

            plan_path = str(planner_result.get("plan_path") or (job_dir / "smart_sync_plan.json"))

            if stop_file.exists() or stop_ev.is_set():
                raise InterruptedError("Stopped after planner stage.")

            # STEP 2: Render
            render_cfg = job_dir / "_render_worker.json"
            render_data = {
                "job_dir": str(job_dir),
                "source_path": str(source_path),
                "plan_path": plan_path,
                "voice": str(job["voice"] or "my-MM-ThihaNeural"),
                "edge_tts_rate": str(settings.get("edge_tts_rate", "+0%")),
                "edge_tts_pitch": str(settings.get("edge_tts_pitch", "+0Hz")),
                "ffmpeg_path": ffmpeg,
                "ffprobe_path": ffprobe,
                "max_video_speed": float(settings.get("max_video_speed", 1.25)),
                "max_video_slow": float(settings.get("max_video_slow", 1.35)),
                "smooth_freeze_fallback": bool(settings.get("smooth_freeze_fallback", False)),
                "max_freeze_hold": float(settings.get("max_freeze_hold", 0.75)),
                "mirror_video": bool(settings.get("mirror_video", False)),
                "zoom_factor": float(settings.get("zoom_factor", 1.05)),
                "render_final_video": True,
                "overlays": settings.get("overlays") or {},
                "voice_volume_percent": int(settings.get("voice_volume_percent", 100)),
                "short_pauses": bool(settings.get("short_pauses", True)),
                "enable_original_background": bool(settings.get("enable_original_background", False)),
                "original_background_volume": int(settings.get("original_background_volume", 25)),
                "output_ratio": str(job["output_ratio"] or "16:9"),
                "frame_fill": str(settings.get("frame_fill", "blur")),
                "stop_file": str(stop_file),
            }
            render_cfg.write_text(json.dumps(render_data, ensure_ascii=False, indent=2), encoding="utf-8")

            render_result = self._run_child(
                job_id,
                "render_worker.py",
                render_cfg,
                "STEP 2 — Edge TTS + Smart Sync",
                run_log,
            ).get("result") or {}

            final_mp4 = render_result.get("final") or str(job_dir / "edge_tts_smart_sync" / "final_edge_tts_smart_sync.mp4")
            if Path(final_mp4).is_file():
                elapsed = time.time() - start_time
                if elapsed >= 60:
                    mins = int(elapsed // 60)
                    secs = int(elapsed % 60)
                    dur_str = f"{mins}m {secs:02d}s ({elapsed:.1f}s)"
                else:
                    dur_str = f"{elapsed:.1f}s"

                success_msg = f"✓ Recap video created successfully! Running duration: {dur_str}. Output: {final_mp4}"
                try:
                    with run_log.open("a", encoding="utf-8", errors="replace") as f:
                        f.write(f"\n{success_msg}\n")
                except Exception:
                    pass
                self._broadcast(job_id, {"kind": "log", "text": success_msg})

                update_job_progress(
                    job_id,
                    status="completed",
                    stage=f"Finished in {dur_str}",
                    current=100,
                    total=100,
                    label=f"Done ({dur_str})",
                    output_video_path=str(final_mp4),
                )
                self._broadcast(job_id, {
                    "kind": "done",
                    "output": final_mp4,
                    "duration_sec": round(elapsed, 1),
                    "duration_str": dur_str,
                })
            else:
                raise RuntimeError(f"Output video file not created: {final_mp4}")

        except InterruptedError as exc:
            update_job_progress(job_id, status="stopped", stage="Stopped", error_message=str(exc))
            self._broadcast(job_id, {"kind": "stopped", "message": str(exc)})
        except Exception as exc:
            err = str(exc)
            update_job_progress(job_id, status="failed", stage="Error", error_message=err)
            self._broadcast(job_id, {"kind": "error", "message": err})
        finally:
            with self._lock:
                self.active_threads.pop(job_id, None)


job_runner = JobRunner()
