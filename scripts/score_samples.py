"""Score our compositions with the official judge's LLMScorer (per-dimension), bypassing tick/expiry.

Composition is the quality model (cached from the submission build, so free); only the judge's
scoring calls cost tokens (gpt-4o-mini).

    python -m scripts.score_samples            # default representative sample
    python -m scripts.score_samples T06 T28    # specific pairs
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from app.config import MODEL_FAST, OPENAI_API_KEY
from app.dataset import load_test_pairs, resolve_pair
from bot import compose

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SIM_PATH = Path(__file__).resolve().parent.parent.parent / "judge_simulator.py"
SAMPLE = ["T01", "T06", "T07", "T09", "T11", "T21", "T24", "T28", "T30"]


def _load_sim():
    spec = importlib.util.spec_from_file_location("judge_simulator", SIM_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.LLM_PROVIDER, mod.LLM_API_KEY, mod.LLM_MODEL = "openai", OPENAI_API_KEY, MODEL_FAST
    return mod


def main():
    ids = sys.argv[1:] or SAMPLE
    sim = _load_sim()
    scorer = sim.LLMScorer(sim.create_provider(), None)
    pairs = {p["test_id"]: p for p in load_test_pairs()}

    dims = ["specificity", "category_fit", "merchant_fit", "decision_quality", "engagement_compulsion"]
    totals = {d: 0 for d in dims}
    n = 0
    for tid in ids:
        t = resolve_pair(pairs[tid])
        msg = compose(t["category"], t["merchant"], t["trigger"], t["customer"])
        s = scorer.score(msg, t["category"], t["merchant"], t["trigger"], t["customer"])
        n += 1
        for d in dims:
            totals[d] += getattr(s, d)
        scope = "cust" if t["customer"] else "mx"
        print(f"{tid} [{t['trigger']['kind']:<20} {scope}]  "
              f"spec={s.specificity} cat={s.category_fit} mx={s.merchant_fit} "
              f"dec={s.decision_quality} eng={s.engagement_compulsion}  TOTAL={s.total}/50")

    print("\n--- AVERAGES (n=%d) ---" % n)
    for d in dims:
        print(f"  {d:24} {totals[d]/n:.1f}/10")
    print(f"  {'AVG TOTAL':24} {sum(totals.values())/n:.1f}/50")


if __name__ == "__main__":
    main()
