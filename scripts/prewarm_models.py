#!/usr/bin/env python3
"""Pre-download and warm up Whisper and Demucs ONNX AI models for instant zero-wait execution."""
from __future__ import annotations

import sys
import time
from pathlib import Path

def prewarm_whisper() -> bool:
    print("⏳ [1/2] Pre-caching Whisper 'small.en' model weights...")
    t0 = time.time()
    try:
        from faster_whisper import WhisperModel
        _ = WhisperModel("small.en", device="cpu", compute_type="int8")
        elapsed = time.time() - t0
        print(f"✅ Whisper 'small.en' model pre-warmed successfully ({elapsed:.1f}s)")
        return True
    except Exception as exc:
        print(f"⚠️ Whisper pre-cache warning: {exc}", file=sys.stderr)
        return False

def prewarm_demucs() -> bool:
    print("⏳ [2/2] Pre-caching Demucs ONNX vocal remover model ('htdemucs_ft_vocals')...")
    t0 = time.time()
    try:
        import demucs_onnx
        res = demucs_onnx.prewarm(["htdemucs_ft_vocals"], precision="fp16weights")
        elapsed = time.time() - t0
        model_path = res.get("vocals") or list(res.values())[0] if res else "cached"
        print(f"✅ Demucs ONNX vocal remover model ready ({elapsed:.1f}s): {model_path}")
        return True
    except Exception as exc:
        print(f"⚠️ Demucs vocal remover pre-cache warning: {exc}", file=sys.stderr)
        return False

def main() -> int:
    print("\n🚀 Pre-warming all AI models to reach 100% Ready Stage...")
    ok_w = prewarm_whisper()
    ok_d = prewarm_demucs()
    if ok_w and ok_d:
        print("🎉 All AI models pre-cached and ready for immediate inference!\n")
        return 0
    print("⚠️ Models finished with warnings (will download on-demand if needed).\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
