"""Drive the official judge_simulator.py against our running bot, using our OpenAI key.

Avoids editing the shared challenge file by importing it and overriding its module globals.

    # server must be running first:  uvicorn app.server:app --port 8080
    python -m scripts.run_judge                 # scenario "all"
    python -m scripts.run_judge phase2_short    # scored compositions
    python -m scripts.run_judge full_evaluation # score across all triggers (expensive)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.config import MODEL_FAST, OPENAI_API_KEY

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SIM_PATH = Path(__file__).resolve().parent.parent.parent / "judge_simulator.py"
BOT_URL = "http://127.0.0.1:8080"


def _load_simulator():
    spec = importlib.util.spec_from_file_location("judge_simulator", SIM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Override config globals the simulator reads at runtime.
    mod.BOT_URL = BOT_URL
    mod.LLM_PROVIDER = "openai"
    mod.LLM_API_KEY = OPENAI_API_KEY
    mod.LLM_MODEL = MODEL_FAST
    return mod


def main():
    scenario = sys.argv[1] if len(sys.argv) > 1 else "all"
    sim = _load_simulator()
    if not OPENAI_API_KEY:
        print("OPENAI_API_KEY not set in environment/.env")
        sys.exit(1)
    llm = sim.create_provider()
    judge = sim.JudgeSimulator(llm)
    ok = judge.run(scenario)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
