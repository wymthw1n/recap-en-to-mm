#!/usr/bin/env python3
"""Pre-download and warm up faster-whisper small.en model."""
import sys
import time

def main():
    print("⏳ Loading / downloading Whisper 'small.en' model weights...")
    start = time.time()
    try:
        from faster_whisper import WhisperModel
        # Device fallback: CPU with INT8 compute type
        model = WhisperModel("small.en", device="cpu", compute_type="int8")
        elapsed = time.time() - start
        print(f"✅ Whisper 'small.en' model ready! (took {elapsed:.1f}s)")
        return 0
    except Exception as exc:
        print(f"❌ Failed to download Whisper model: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
