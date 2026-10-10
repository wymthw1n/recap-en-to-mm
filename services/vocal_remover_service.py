from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]
def _noop(_: str) -> None:
    pass


class VocalRemoverService:
    """Isolates background audio (BGM, sound effects, ambience) from source video

    by removing English speech/vocals using ONNX-accelerated stem separation.
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg", log: LogFn = _noop) -> None:
        self.ffmpeg = ffmpeg_path
        self.log = log

    def extract_clean_background(
        self,
        source_video: Path,
        output_bg_wav: Path,
        work_dir: Path,
        cache_path: Path | None = None,
    ) -> Path:
        source_video = Path(source_video).resolve()
        output_bg_wav = Path(output_bg_wav).resolve()
        work_dir = Path(work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        output_bg_wav.parent.mkdir(parents=True, exist_ok=True)

        # Check cache first
        if cache_path and Path(cache_path).is_file() and Path(cache_path).stat().st_size > 10000:
            self.log(f"♻️ Reusing cached clean background audio: {Path(cache_path).name}")
            if Path(cache_path).resolve() != output_bg_wav:
                import shutil
                shutil.copy2(cache_path, output_bg_wav)
            return output_bg_wav

        # Step 1: Extract full 44.1kHz stereo audio from source video
        self.log("🔊 Extracting audio from source video for vocal separation...")
        extracted_audio = work_dir / "source_full_audio_44k.wav"
        cmd = [
            self.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source_video),
            "-vn", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
            str(extracted_audio),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0 or not extracted_audio.is_file():
            raise RuntimeError(f"Audio extraction from source video failed:\n{res.stderr[-2000:]}")

        # Step 2: Separate vocals using ONNX Runtime
        self.log("🎙️ Separating speech vocals from original video audio (demucs-onnx)...")
        t0 = time.time()
        try:
            import numpy as np
            import soundfile as sf
            from demucs_onnx import separate_stem

            orig_audio, sample_rate = sf.read(str(extracted_audio))
            # Format to (channels, samples)
            if orig_audio.ndim == 1:
                orig_audio = np.stack([orig_audio, orig_audio], axis=0)
            else:
                orig_audio = orig_audio.T

            # Run ONNX vocal separation (fp16weights for fast CPU/GPU inference)
            vocals = separate_stem(str(extracted_audio), "vocals", precision="fp16weights")

            # Background = original audio minus vocals
            min_len = min(orig_audio.shape[1], vocals.shape[1])
            bg_audio = orig_audio[:, :min_len] - vocals[:, :min_len]
            bg_audio = np.clip(bg_audio, -1.0, 1.0)

            # Write background audio
            sf.write(str(output_bg_wav), bg_audio.T, sample_rate)
            duration = min_len / float(sample_rate)
            elapsed = time.time() - t0
            self.log(
                f"✅ Background sound isolated ({duration:.1f}s) in {elapsed:.1f}s — "
                "English speech removed, BGM & SFX retained!"
            )

            if cache_path:
                import shutil
                shutil.copy2(output_bg_wav, cache_path)

            extracted_audio.unlink(missing_ok=True)
            return output_bg_wav

        except Exception as exc:
            self.log(f"⚠️ Vocal separation error ({exc}); checking fallback...")
            raise RuntimeError(f"Vocal separation failed: {exc}") from exc
