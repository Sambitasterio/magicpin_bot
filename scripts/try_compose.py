"""Dev harness: compose for a few representative tuples and print the result.

Usage:
    python -m scripts.try_compose            # runs a curated sample set
    python -m scripts.try_compose T28 T09    # run specific test_pair ids
"""
from __future__ import annotations

import sys

# Windows consoles default to cp1252 and choke on ₹/emoji — force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.composer.core import compose
from app.dataset import (
    load_category,
    load_customer,
    load_merchant,
    load_test_pairs,
    load_trigger,
    resolve_pair,
)

# A few hand-picked tuples that mirror the case studies (some are seed triggers, not test pairs).
SAMPLES = [
    # (label, trigger_id, merchant_id, customer_id)
    ("CS1 dentist research-digest", "trg_001_research_digest_dentists", "m_001_drmeera_dentist_delhi", None),
    ("CS2 dentist recall (customer)", "trg_003_recall_due_priya", "m_001_drmeera_dentist_delhi", "c_001_priya_for_m001"),
    ("CS5 restaurant IPL", "trg_010_ipl_match_delhi", "m_005_pizzajunction_restaurant_delhi", None),
    ("CS9 pharmacy supply alert", "trg_018_supply_atorvastatin_recall", "m_009_apollo_pharmacy_jaipur", None),
    ("competitor opened (dentist)", "trg_023_competitor_opened_dentist", "m_001_drmeera_dentist_delhi", None),
    ("regulation change (dentist)", "trg_002_compliance_dci_radiograph", "m_001_drmeera_dentist_delhi", None),
]


def _run(label, trigger, merchant, customer):
    cat = load_category(merchant["category_slug"])
    out = compose(cat, merchant, trigger, customer)
    print("=" * 78)
    print(label, f"[{trigger.get('kind')}]")
    print("-" * 78)
    print("BODY:", out["body"])
    print(f"\nCTA: {out['cta']}   SEND_AS: {out['send_as']}   SUPPRESS: {out['suppression_key']}")
    print("RATIONALE:", out["rationale"])
    print()


def main():
    args = [a for a in sys.argv[1:]]
    if args:
        pairs = {p["test_id"]: p for p in load_test_pairs()}
        for tid in args:
            p = pairs[tid]
            t = resolve_pair(p)
            _run(f"{tid}", t["trigger"], t["merchant"], t["customer"])
        return
    for label, trg_id, mid, cid in SAMPLES:
        trigger = load_trigger(trg_id)
        merchant = load_merchant(mid)
        customer = load_customer(cid) if cid else None
        _run(label, trigger, merchant, customer)


if __name__ == "__main__":
    main()
