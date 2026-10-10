from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key, unset_key

from web.storage import ROOT_DIR

ENV_PATH = ROOT_DIR / ".env"
CONFIG_PATH = ROOT_DIR / "config.json"


def _mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return key[:2] + "..." + key[-2:]
    return key[:6] + "..." + key[-4:]


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.is_file():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def get_settings() -> dict[str, Any]:
    env_vals = dotenv_values(ENV_PATH) if ENV_PATH.is_file() else {}
    cfg = load_config()

    primary_key = env_vals.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")
    proxy = env_vals.get("GEMINI_PROXY") or os.environ.get("GEMINI_PROXY", "")

    # Collect project fallback keys
    fallback_keys = []
    for k, v in env_vals.items():
        if k.startswith("GEMINI_IMAGE_PROJECT_") and v:
            fallback_keys.append({"name": k, "key": v, "masked": _mask_key(v)})

    return {
        "gemini_api_key": primary_key,
        "gemini_api_key_masked": _mask_key(primary_key),
        "fallback_keys": fallback_keys,
        "gemini_proxy": proxy,
        "gemini_text_model": cfg.get("gemini_text_model", "gemini-3.5-flash"),
        "edge_tts_voice": cfg.get("edge_tts_voice", "my-MM-ThihaNeural"),
        "edge_tts_rate": cfg.get("edge_tts_rate", "+0%"),
        "max_video_speed": cfg.get("max_video_speed", 1.25),
        "output_ratio": cfg.get("output_ratio", "16:9"),
        "frame_fill": cfg.get("frame_fill", "blur"),
        "short_pauses": cfg.get("short_pauses", True),
    }


def update_settings(data: dict[str, Any]) -> dict[str, Any]:
    if not ENV_PATH.exists():
        ENV_PATH.write_text("", encoding="utf-8")

    # Update primary key if provided
    if "gemini_api_key" in data:
        val = str(data["gemini_api_key"] or "").strip()
        if val and not val.startswith("AIzaSy...") and "..." not in val:
            set_key(str(ENV_PATH), "GEMINI_API_KEY", val)
            os.environ["GEMINI_API_KEY"] = val

    # Update proxy
    if "gemini_proxy" in data:
        proxy_val = str(data["gemini_proxy"] or "").strip()
        set_key(str(ENV_PATH), "GEMINI_PROXY", proxy_val)
        if proxy_val:
            os.environ["GEMINI_PROXY"] = proxy_val
        else:
            os.environ.pop("GEMINI_PROXY", None)

    # Update fallback keys if provided
    if "fallback_keys" in data and isinstance(data["fallback_keys"], list):
        # Clear existing GEMINI_IMAGE_PROJECT_*
        env_vals = dotenv_values(ENV_PATH)
        for k in env_vals:
            if k.startswith("GEMINI_IMAGE_PROJECT_"):
                unset_key(str(ENV_PATH), k)
                os.environ.pop(k, None)

        # Set new
        for idx, item in enumerate(data["fallback_keys"], start=1):
            k_val = str(item.get("key") or "").strip()
            if k_val and "..." not in k_val:
                key_name = f"GEMINI_IMAGE_PROJECT_{idx}_KEY"
                set_key(str(ENV_PATH), key_name, k_val)
                os.environ[key_name] = k_val

    # Update config.json
    cfg = load_config()
    for prop in [
        "gemini_text_model",
        "edge_tts_voice",
        "edge_tts_rate",
        "max_video_speed",
        "output_ratio",
        "frame_fill",
        "short_pauses",
    ]:
        if prop in data:
            cfg[prop] = data[prop]
    save_config(cfg)

    return get_settings()


def test_gemini_key(api_key: str, proxy: str = "") -> dict[str, Any]:
    key = api_key.strip()
    if not key or "..." in key:
        # Load saved if masked or empty
        env_vals = dotenv_values(ENV_PATH) if ENV_PATH.is_file() else {}
        key = env_vals.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", "")

    if not key:
        return {"ok": False, "message": "No API key provided"}

    try:
        from google import genai
        from google.genai import types

        client_kwargs: dict[str, Any] = {"api_key": key}
        if proxy:
            import httpx
            client_kwargs["http_client"] = httpx.Client(proxy=proxy, timeout=15.0)

        client = genai.Client(**client_kwargs)
        # Fast lightweight probe
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say 'OK' only.",
            config=types.GenerateContentConfig(max_output_tokens=10),
        )
        text = getattr(resp, "text", "") or ""
        return {"ok": True, "message": f"Valid key. Response: {text.strip()[:30]}"}
    except Exception as exc:
        msg = str(exc)
        if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
            return {"ok": False, "message": "Key valid but quota exhausted (429)"}
        if "API_KEY_INVALID" in msg or "400" in msg:
            return {"ok": False, "message": "API key invalid or disabled"}
        return {"ok": False, "message": f"Validation failed: {msg[:120]}"}
