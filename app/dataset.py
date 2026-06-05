"""Load the expanded challenge dataset and resolve (category, merchant, trigger, customer) tuples.

Used for local development and to build the static submission.jsonl. The live server does NOT
read these files — it gets contexts pushed over /v1/context — but the shapes are identical.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .config import DATA_DIR


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def load_category(slug: str) -> dict:
    return _read(DATA_DIR / "categories" / f"{slug}.json")


@lru_cache(maxsize=None)
def load_merchant(merchant_id: str) -> dict:
    return _read(DATA_DIR / "merchants" / f"{merchant_id}.json")


@lru_cache(maxsize=None)
def load_trigger(trigger_id: str) -> dict:
    return _read(DATA_DIR / "triggers" / f"{trigger_id}.json")


@lru_cache(maxsize=None)
def load_customer(customer_id: str) -> dict:
    return _read(DATA_DIR / "customers" / f"{customer_id}.json")


def load_test_pairs() -> list[dict]:
    return _read(DATA_DIR / "test_pairs.json")["pairs"]


def resolve_pair(pair: dict) -> dict:
    """Given a test_pairs entry, return the full {category, merchant, trigger, customer} tuple."""
    merchant = load_merchant(pair["merchant_id"])
    trigger = load_trigger(pair["trigger_id"])
    category = load_category(merchant["category_slug"])
    customer: Optional[dict] = (
        load_customer(pair["customer_id"]) if pair.get("customer_id") else None
    )
    return {
        "test_id": pair.get("test_id"),
        "category": category,
        "merchant": merchant,
        "trigger": trigger,
        "customer": customer,
    }


if __name__ == "__main__":
    # Smoke test: resolve all 30 test pairs and print a compact summary.
    pairs = load_test_pairs()
    print(f"Loaded {len(pairs)} test pairs")
    for p in pairs:
        t = resolve_pair(p)
        scope = "customer" if t["customer"] else "merchant"
        print(
            f"  {t['test_id']}: {t['merchant']['category_slug']:<11} "
            f"{t['trigger']['kind']:<22} scope={scope}"
        )
