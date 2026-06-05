"""Central configuration. Loads .env once and exposes settings used across the app."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv optional at runtime
    pass

# Project paths
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "expanded"

# LLM provider (OpenAI)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL_QUALITY = os.getenv("VERA_MODEL_QUALITY", "gpt-4o")
MODEL_FAST = os.getenv("VERA_MODEL_FAST", "gpt-4o-mini")
TEMPERATURE = float(os.getenv("VERA_TEMPERATURE", "0"))
SEED = int(os.getenv("VERA_SEED", "20260426"))


def has_api_key() -> bool:
    return bool(OPENAI_API_KEY)
