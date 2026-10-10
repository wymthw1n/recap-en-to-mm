from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any


CONSONANT_RANGE = r"[\u1000-\u1021\u1023-\u102A\u103F\u104C-\u104F]"
BURMESE_CHAR = r"[\u1000-\u102A\u103B-\u103E\u1039\u103F\u104C-\u104F]"
_re_leading_e = re.compile(rf"(?<!{BURMESE_CHAR})\u1031({CONSONANT_RANGE})")
_re_leading_ra = re.compile(rf"(?<!{BURMESE_CHAR})\u103C({CONSONANT_RANGE})")


def normalize_burmese_text(text: str) -> str:
    """Normalizes Burmese text to canonical Unicode 5.1+ standard.

    - Canonical Unicode NFC normalization.
    - Fixes orphaned leading signs (ေ U+1031 or ြ U+103C typed before consonant).
    - Canonical diacritic reordering within syllable clusters.
    """
    if not text or not isinstance(text, str):
        return ""

    text = unicodedata.normalize("NFC", text)

    # Fix orphaned leading 'ေ' (U+1031) or 'ြ' (U+103C) typed before consonant
    text = _re_leading_e.sub(r"\g<1>" + "\u1031", text)
    text = _re_leading_ra.sub(r"\g<1>" + "\u103C", text)

    # Medials must come before Vowel E (\u1031) and other vowels
    while re.search(r"([\u1031\u102B-\u1032\u1036\u1037\u1038])([\u103B-\u103E])", text):
        text = re.sub(r"([\u1031\u102B-\u1032\u1036\u1037\u1038])([\u103B-\u103E])", r"\2\1", text)

    # Vowel E (\u1031) must come before other vowels/anusvara/asat/dot below/visarga
    while re.search(r"([\u102B-\u1030\u1032\u1036\u1037\u1038\u103A])(\u1031)", text):
        text = re.sub(r"([\u102B-\u1030\u1032\u1036\u1037\u1038\u103A])(\u1031)", r"\2\1", text)

    # Dot below (\u1037) must come after vowels and anusvara (\u1036)
    while re.search(r"(\u1037)([\u102B-\u1032\u1036])", text):
        text = re.sub(r"(\u1037)([\u102B-\u1032\u1036])", r"\2\1", text)

    # Visarga (\u1038) must come last in cluster
    while re.search(r"(\u1038)([\u1037\u103A])", text):
        text = re.sub(r"(\u1038)([\u1037\u103A])", r"\2\1", text)

    return unicodedata.normalize("NFC", text).strip()


def wrap_burmese_lines(text: str, max_chars_per_line: int = 34) -> str:
    """Wraps Burmese text cleanly into 1-2 lines without breaking syllables or combining marks."""
    text = normalize_burmese_text(text)
    if len(text) <= max_chars_per_line:
        return text

    if "\n" in text:
        return "\n".join(wrap_burmese_lines(line, max_chars_per_line) for line in text.split("\n"))

    words = text.split(" ")
    if len(words) > 1:
        total_len = len(text)
        best_i = 1
        best_diff = total_len
        for i in range(1, len(words)):
            l1 = " ".join(words[:i])
            diff = abs(len(l1) - (total_len / 2))
            if diff < best_diff:
                best_diff = diff
                best_i = i
        return " ".join(words[:best_i]) + "\n" + " ".join(words[best_i:])

    # Fallback to syllable boundaries (consonant/independent vowel followed by marks)
    syllables = re.findall(r"[\u1000-\u102A\u103F\u104C-\u104F][^\u1000-\u102A\u103F\u104C-\u104F]*", text) or [text]
    if len(syllables) > 1:
        total_len = sum(len(s) for s in syllables)
        best_i = 1
        best_diff = total_len
        accum = 0
        for i, s in enumerate(syllables):
            accum += len(s)
            diff = abs(accum - (total_len / 2))
            if diff < best_diff:
                best_diff = diff
                best_i = i + 1
        return "".join(syllables[:best_i]) + "\n" + "".join(syllables[best_i:])

    return text


class SubtitleService:
    @staticmethod
    def format_timestamp_srt(seconds: float) -> str:
        s = max(0.0, float(seconds))
        hours = int(s // 3600)
        minutes = int((s % 3600) // 60)
        secs = int(s % 60)
        milli = int(round((s - int(s)) * 1000))
        if milli >= 1000:
            secs += 1
            milli -= 1000
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milli:03d}"

    @staticmethod
    def format_timestamp_ass(seconds: float) -> str:
        s = max(0.0, float(seconds))
        hours = int(s // 3600)
        minutes = int((s % 3600) // 60)
        secs = int(s % 60)
        centi = int(round((s - int(s)) * 100))
        if centi >= 100:
            secs += 1
            centi -= 100
        return f"{hours:01d}:{minutes:02d}:{secs:02d}.{centi:02d}"

    @staticmethod
    def _hex_to_ass_color(hex_color: str, alpha_hex: str = "00") -> str:
        clean = str(hex_color or "#FFDE00").lstrip("#").strip()
        if len(clean) == 6:
            r = clean[0:2]
            g = clean[2:4]
            b = clean[4:6]
            return f"&H{alpha_hex}{b}{g}{r}&"
        return f"&H{alpha_hex}00DEFF&"

    def generate_srt(
        self,
        timed_segments: list[dict[str, Any]],
        output_path: Path,
        max_chars_per_line: int = 34,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for i, seg in enumerate(timed_segments, start=1):
            start = seg.get("audio_start") if "audio_start" in seg else seg.get("start", 0.0)
            end = seg.get("audio_end") if "audio_end" in seg else seg.get("end", 0.0)
            text = str(seg.get("narration") or seg.get("text") or "").strip()
            if not text:
                continue
            wrapped = wrap_burmese_lines(text, max_chars_per_line=max_chars_per_line)
            lines.append(f"{i}\n{self.format_timestamp_srt(float(start))} --> {self.format_timestamp_srt(float(end))}\n{wrapped}\n")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    def generate_ass(
        self,
        timed_segments: list[dict[str, Any]],
        output_path: Path,
        *,
        font_name: str = "Noto Sans Myanmar",
        font_color: str = "#FFDE00",
        font_size: float = 3.6,
        position: list[float] | None = None,
        style: str = "outline",
        video_width: int = 1080,
        video_height: int = 1920,
        box_width_percent: float = 85.0,
        max_chars_per_line: int | None = None,
    ) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        fw = int(video_width or 1080)
        fh = int(video_height or 1920)

        # Resolution-relative font sizing (percentage of video height):
        # If font_size <= 12.0: font_size is percentage of video height (e.g. 3.6 -> 3.6% of frame height)
        # If font_size > 12.0: legacy pixel size mapped to height percentage
        fs_val = float(font_size or 3.6)
        if fs_val <= 12.0:
            size_pct = fs_val
        else:
            # Map legacy 34px (at 720p baseline) to ~3.5%
            size_pct = max(1.8, min(8.0, (fs_val / 720.0) * 100.0 * 0.75))

        # Scaled font size strictly proportional to video height fh
        scaled_font_size = max(16, int(round(fh * (size_pct / 100.0))))

        pos = position or [0.50, 0.86]
        pos_x = float(pos[0]) if len(pos) > 0 else 0.50
        pos_y = float(pos[1]) if len(pos) > 1 else 0.86

        target_x = int(round(pos_x * fw))
        target_y = int(round(pos_y * fh))

        # Dynamic max_chars_per_line based on box width and scaled font size
        box_pct = max(40.0, min(95.0, float(box_width_percent or 85.0)))
        available_px = fw * (box_pct / 100.0)
        if max_chars_per_line is None:
            # Burmese glyph average width is approx 0.65-0.70 of font size
            computed_chars = int(available_px / max(12, scaled_font_size * 0.68))
            chars_per_line = max(18, min(65, computed_chars))
        else:
            chars_per_line = max_chars_per_line

        # Primary text color in ASS &H00BBGGRR&
        ass_primary = self._hex_to_ass_color(font_color, "00")
        ass_outline_col = "&H00000000&"  # Solid black outline
        ass_shadow_col = "&H80000000&"   # 50% opacity shadow

        # BorderStyle: 1 = outline + drop shadow, 3 = opaque bounding box
        has_box = (str(style).lower() == "box")
        border_style = 3 if has_box else 1
        outline = max(2.0, round(scaled_font_size * 0.08, 1)) if not has_box else 2.0
        shadow = max(1.0, round(scaled_font_size * 0.05, 1)) if not has_box else 0.0
        back_col = "&H80000000&" if has_box else ass_shadow_col

        margin_l = max(20, int(round(fw * 0.04)))
        margin_r = margin_l
        margin_v = max(10, int(round(fh * 0.02)))

        ass_content = f"""[Script Info]
Title: Burmese Recap Subtitles
ScriptType: v4.00+
WrapStyle: 2
PlayResX: {fw}
PlayResY: {fh}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: RecapSubs,{font_name},{scaled_font_size},{ass_primary},&H000000FF&,{ass_outline_col},{back_col},-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},5,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        events: list[str] = []
        for seg in timed_segments:
            start = seg.get("audio_start") if "audio_start" in seg else seg.get("start", 0.0)
            end = seg.get("audio_end") if "audio_end" in seg else seg.get("end", 0.0)
            text = str(seg.get("narration") or seg.get("text") or "").strip()
            if not text:
                continue
            wrapped = wrap_burmese_lines(text, max_chars_per_line=chars_per_line)
            ass_text = wrapped.replace("\n", "\\N")
            start_str = self.format_timestamp_ass(float(start))
            end_str = self.format_timestamp_ass(float(end))
            # \\an5 ensures middle-center anchor where ALL lines in multi-line text are center-aligned at target_x
            override_tag = r"{\an5\pos(" + f"{target_x},{target_y}" + r")}"
            events.append(f"Dialogue: 0,{start_str},{end_str},RecapSubs,,0,0,0,,{override_tag}{ass_text}")

        ass_content += "\n".join(events) + "\n"
        output_path.write_text(ass_content, encoding="utf-8")
        return output_path
