"""Build submission.jsonl — one composed message per canonical test pair (30 lines).

Uses the quality model (gpt-4o by default) since there's no latency pressure here.

    python -m scripts.build_submission           # writes ./submission.jsonl
    python -m scripts.build_submission --out x    # custom path
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.config import MODEL_QUALITY
from app.dataset import load_test_pairs, resolve_pair
from bot import compose

SUBMISSION_KEYS = ["test_id", "body", "cta", "send_as", "suppression_key", "rationale"]


def build(out_path: Path) -> list[dict]:
    rows: list[dict] = []
    for pair in load_test_pairs():
        t = resolve_pair(pair)
        msg = compose(t["category"], t["merchant"], t["trigger"], t["customer"])
        rows.append({
            "test_id": t["test_id"],
            "body": msg["body"],
            "cta": msg["cta"],
            "send_as": msg["send_as"],
            "suppression_key": msg["suppression_key"],
            "rationale": msg["rationale"],
        })
        scope = "customer" if t["customer"] else "merchant"
        print(f"  {t['test_id']:>3} [{t['trigger']['kind']:<22} {scope:<8}] {msg['body'][:60]}…")

    with open(out_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="submission.jsonl")
    args = ap.parse_args()
    print(f"Composing 30 test pairs with {MODEL_QUALITY} -> {args.out}")
    rows = build(Path(args.out))
    print(f"\nWrote {len(rows)} lines to {args.out}")


if __name__ == "__main__":
    main()
