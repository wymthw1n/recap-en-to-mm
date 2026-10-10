import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.subtitle_service import (
    SubtitleService,
    normalize_burmese_text,
    wrap_burmese_lines,
)
from app.core import apply_production_overlays


class TestSubtitleService(unittest.TestCase):
    def setUp(self):
        self.service = SubtitleService()

    def test_normalize_burmese_text(self):
        # Orphaned leading 'ေ' before consonant 'က' -> 'ကေ'
        text_with_orphaned_e = "\u1031\u1000"
        normalized = normalize_burmese_text(text_with_orphaned_e)
        self.assertEqual(normalized, "\u1000\u1031")

        # Standard text preserved and normalized to NFC
        sample = "ဒါကတော့ မြန်မာစာတန်းထိုး ဖြစ်ပါတယ်"
        self.assertEqual(normalize_burmese_text(sample), sample)

    def test_wrap_burmese_lines(self):
        short_text = "မင်္ဂလာပါ"
        self.assertEqual(wrap_burmese_lines(short_text, max_chars_per_line=30), short_text)

        long_text = "ယခုဗီဒီယိုတွင် လူကြိုက်အများဆုံး ဇာတ်ကားတစ်ကားဖြစ်သည့် ရုပ်ရှင်အကြောင်းကို အသေးစိတ် ပြန်လည်တင်ဆက်ပေးထားပါသည်"
        wrapped = wrap_burmese_lines(long_text, max_chars_per_line=30)
        self.assertIn("\n", wrapped)

    def test_generate_srt(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_srt = Path(tmp_dir) / "test.srt"
            segments = [
                {
                    "audio_start": 1.25,
                    "audio_end": 4.50,
                    "narration": "မင်္ဂလာပါ ခင်ဗျာ။",
                },
                {
                    "audio_start": 4.80,
                    "audio_end": 8.10,
                    "narration": "ဇာတ်လမ်းစတင်ပါပြီ။",
                },
            ]
            self.service.generate_srt(segments, out_srt)
            self.assertTrue(out_srt.is_file())
            content = out_srt.read_text(encoding="utf-8")
            self.assertIn("00:00:01,250 --> 00:00:04,500", content)
            self.assertIn("မင်္ဂလာပါ ခင်ဗျာ။", content)
            self.assertIn("00:00:04,800 --> 00:00:08,100", content)
            self.assertIn("ဇာတ်လမ်းစတင်ပါပြီ။", content)

    def test_generate_ass(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_ass = Path(tmp_dir) / "test.ass"
            segments = [
                {
                    "audio_start": 0.50,
                    "audio_end": 3.75,
                    "narration": "ဒါကတော့ ပထမစာတန်းထိုး ဖြစ်ပါတယ်",
                }
            ]
            self.service.generate_ass(
                segments,
                out_ass,
                font_name="Noto Sans Myanmar",
                font_color="#FFDE00",
                font_size=34,
                position=[0.50, 0.86],
                style="outline",
                video_width=1080,
                video_height=1920,
            )
            self.assertTrue(out_ass.is_file())
            content = out_ass.read_text(encoding="utf-8")
            self.assertIn("[Script Info]", content)
            self.assertIn("PlayResX: 1080", content)
            self.assertIn("PlayResY: 1920", content)
            self.assertIn("Style: RecapSubs", content)
            # Yellow #FFDE00 -> BGR &H0000DEFF&
            self.assertIn("&H0000DEFF&", content)
            self.assertIn("Dialogue: 0,0:00:00.50,0:00:03.75,RecapSubs", content)

    def test_generate_ass_box_style(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_ass = Path(tmp_dir) / "box.ass"
            segments = [
                {
                    "audio_start": 1.0,
                    "audio_end": 2.0,
                    "narration": "Box Style Subtitle",
                }
            ]
            self.service.generate_ass(
                segments,
                out_ass,
                style="box",
            )
            content = out_ass.read_text(encoding="utf-8")
            # BorderStyle 3 indicates bounding box in ASS
            self.assertIn(",3,", content)

    def test_apply_production_overlays_ordering(self):
        from unittest.mock import patch, MagicMock
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_in = tmp / "in.mp4"
            fake_in.write_bytes(b"0" * 1000)
            fake_out = tmp / "out.mp4"
            fake_ass = tmp / "sub.ass"
            fake_ass.write_text("dummy", encoding="utf-8")
            overlays = {
                "blur_boxes": [{"x": 0.1, "y": 0.8, "w": 0.5, "h": 0.1}],
                "blur_strength": 18,
                "burn_subtitles": True,
                "subtitles_ass_path": str(fake_ass),
            }
            with patch("subprocess.run") as mock_run:
                def fake_run(cmd, **kwargs):
                    fake_out.write_bytes(b"0" * 6000)
                    m = MagicMock()
                    m.returncode = 0
                    m.stderr = ""
                    return m
                mock_run.side_effect = fake_run

                apply_production_overlays(
                    ffmpeg="ffmpeg",
                    input_video=fake_in,
                    output_video=fake_out,
                    overlays=overlays,
                    encoder="libx264",
                    work_dir=tmp,
                    frame_size=(1080, 1920),
                )
                self.assertTrue(mock_run.called)
                cmd = mock_run.call_args[0][0]
                filter_complex_idx = cmd.index("-filter_complex")
                graph = cmd[filter_complex_idx + 1]

                # boxblur must appear before ass filter in filter chain
                blur_idx = graph.find("boxblur")
                ass_idx = graph.find("ass=filename=")
                self.assertGreater(blur_idx, -1)
                self.assertGreater(ass_idx, -1)
                self.assertLess(blur_idx, ass_idx, "Subtitles must be rendered AFTER boxblur")

    def test_generate_ass_resolution_proportional_and_center_alignment(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_ass_1080p = Path(tmp_dir) / "1080p.ass"
            out_ass_720p = Path(tmp_dir) / "720p.ass"
            segments = [
                {
                    "audio_start": 0.0,
                    "audio_end": 2.5,
                    "narration": "ဒါကတော့ မြန်မာစာတန်းထိုး နမူနာ ဖြစ်ပါတယ် စာကြောင်း အရှည် ဖြစ်ပါသည်",
                }
            ]

            # 1. 1080x1920 vertical format
            self.service.generate_ass(
                segments,
                out_ass_1080p,
                font_size=3.6,
                position=[0.50, 0.86],
                video_width=1080,
                video_height=1920,
                box_width_percent=85.0,
            )
            content_1080p = out_ass_1080p.read_text(encoding="utf-8")
            # 1920 * 0.036 = 69
            self.assertIn(",69,", content_1080p)
            # Centering override tag {\an5\pos(540,1651)}
            self.assertIn(r"{\an5\pos(540,1651)}", content_1080p)
            self.assertIn("Alignment", content_1080p)
            self.assertIn("WrapStyle: 2", content_1080p)

            # 2. 1280x720 horizontal format
            self.service.generate_ass(
                segments,
                out_ass_720p,
                font_size=3.6,
                position=[0.50, 0.86],
                video_width=1280,
                video_height=720,
                box_width_percent=85.0,
            )
            content_720p = out_ass_720p.read_text(encoding="utf-8")
            # 720 * 0.036 = 26
            self.assertIn(",26,", content_720p)
            # Centering override tag {\an5\pos(640,619)}
            self.assertIn(r"{\an5\pos(640,619)}", content_720p)


if __name__ == "__main__":
    unittest.main()
