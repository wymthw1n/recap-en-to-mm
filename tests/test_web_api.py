from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.main import app
from web.storage import delete_source, insert_source, list_sources, list_jobs, delete_job


class WebApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_check(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("app"), "recap-en-to-mm")

    def test_index_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Recap Production", resp.text)
        self.assertIn("English → Myanmar", resp.text)

    def test_settings_lifecycle(self):
        # 1. Get settings
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("gemini_text_model", data)
        self.assertIn("edge_tts_voice", data)

        # 2. Update settings
        payload = {
            "edge_tts_voice": "my-MM-NilarNeural",
            "gemini_text_model": "gemini-3.5-flash-lite",
            "max_video_speed": 1.20,
        }
        update_resp = self.client.post("/api/settings", json=payload)
        self.assertEqual(update_resp.status_code, 200)
        updated = update_resp.json()
        self.assertEqual(updated.get("edge_tts_voice"), "my-MM-NilarNeural")
        self.assertEqual(updated.get("gemini_text_model"), "gemini-3.5-flash-lite")

    def test_sources_and_jobs_storage(self):
        # Insert mock source
        src_id = "test_src_001"
        insert_source(
            source_id=src_id,
            name="Test Video",
            filename="test_video.mp4",
            source_type="upload",
            duration=30.0,
            width=1920,
            height=1080,
            file_size=10240,
        )

        resp = self.client.get("/api/sources")
        self.assertEqual(resp.status_code, 200)
        sources = resp.json()
        found = next((s for s in sources if s["id"] == src_id), None)
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "Test Video")

        # Cleanup source
        delete_source(src_id)
        resp2 = self.client.get("/api/sources")
        self.assertIsNone(next((s for s in resp2.json() if s["id"] == src_id), None))

    def test_preview_frame_missing_source(self):
        resp = self.client.get("/api/preview/frame?source_id=nonexistent&time=1.0")
        self.assertEqual(resp.status_code, 404)

    def test_subtitles_and_orig_bg_ui_elements(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('id="burnSubtitlesCheck"', resp.text)
        self.assertIn('id="subSizeSlider"', resp.text)
        self.assertIn('id="enableOrigBgCheck"', resp.text)
        self.assertIn('id="origBgVolSlider"', resp.text)
        self.assertIn('id="overlaySubtitle"', resp.text)
        self.assertIn('id="modalDownloadSrt"', resp.text)
        self.assertIn('id="modalDownloadAss"', resp.text)

    def test_subtitle_download_endpoints(self):
        import tempfile
        from web.storage import insert_or_update_job
        with tempfile.TemporaryDirectory() as tmp_dir:
            job_id = "test_sub_job_123"
            job_dir = Path(tmp_dir) / job_id
            job_dir.mkdir(parents=True, exist_ok=True)
            srt_path = job_dir / "subtitles.srt"
            ass_path = job_dir / "subtitles.ass"
            srt_path.write_text("1\n00:00:01,000 --> 00:00:03,000\nစမ်းသပ်ချက်\n", encoding="utf-8")
            ass_path.write_text("[Script Info]\nTitle: Test\n", encoding="utf-8")

            insert_or_update_job(
                job_id=job_id,
                source_id="src_dummy",
                source_title="Test Video",
                source_path="/dummy/path.mp4",
                status="completed",
                stage="Done",
                voice="my-MM-ThihaNeural",
                output_ratio="16:9",
                job_dir=str(job_dir),
            )

            # Test SRT download
            resp_srt = self.client.get(f"/api/jobs/{job_id}/subtitles.srt")
            self.assertEqual(resp_srt.status_code, 200)
            self.assertIn("စမ်းသပ်ချက်", resp_srt.text)

            # Test ASS download
            resp_ass = self.client.get(f"/api/jobs/{job_id}/subtitles.ass")
            self.assertEqual(resp_ass.status_code, 200)
            self.assertIn("[Script Info]", resp_ass.text)

            delete_job(job_id)


if __name__ == "__main__":
    unittest.main()
