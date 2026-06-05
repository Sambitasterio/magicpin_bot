"""Phase 1 validation tests.

Validator tests are pure (no API). Compose tests rely on the on-disk LLM cache (populated by
`python -m scripts.try_compose`) so they're deterministic and don't spend tokens in CI.
"""
from __future__ import annotations

import pytest

from app.composer.core import compose
from app.composer.validate import validate
from app.dataset import load_category, load_customer, load_merchant, load_trigger

CTX = "context with 38% and 62% and JIDA"


# ---------- validator (pure) ----------

def test_validate_clean():
    r = {"body": "Worth a look — 38% better.", "cta": "open_ended", "send_as": "vera", "rationale": "x"}
    assert validate(r, "vera", CTX) == []


def test_validate_url_rejected():
    r = {"body": "See https://magicpin.com", "cta": "none", "send_as": "vera", "rationale": "x"}
    assert any("URL" in e for e in validate(r, "vera", CTX))


def test_validate_empty_body():
    r = {"body": "  ", "cta": "none", "send_as": "vera", "rationale": "x"}
    assert any("body is empty" in e for e in validate(r, "vera", CTX))


def test_validate_bad_cta():
    r = {"body": "hi", "cta": "reply_now", "send_as": "vera", "rationale": "x"}
    assert any("cta must be one of" in e for e in validate(r, "vera", CTX))


def test_validate_send_as_mismatch():
    r = {"body": "hi", "cta": "none", "send_as": "vera", "rationale": "x"}
    assert any("send_as must be" in e for e in validate(r, "merchant_on_behalf", CTX))


def test_validate_stacked_cta():
    body = "Reply YES for this, reply NO for that, reply MAYBE for later."
    r = {"body": body, "cta": "open_ended", "send_as": "vera", "rationale": "x"}
    assert any("stacked CTA" in e for e in validate(r, "vera", CTX))


def test_validate_ungrounded_percentage():
    r = {"body": "Your sales jumped 99% this week!", "cta": "none", "send_as": "vera", "rationale": "x"}
    assert any("99% is not in the contexts" in e for e in validate(r, "vera", CTX))


# ---------- compose (cached) ----------

@pytest.mark.parametrize("trg,mid,cid,expect", [
    ("trg_001_research_digest_dentists", "m_001_drmeera_dentist_delhi", None, "vera"),
    ("trg_003_recall_due_priya", "m_001_drmeera_dentist_delhi", "c_001_priya_for_m001", "merchant_on_behalf"),
])
def test_send_as_logic(trg, mid, cid, expect):
    m = load_merchant(mid)
    out = compose(load_category(m["category_slug"]), m, load_trigger(trg),
                  load_customer(cid) if cid else None)
    assert out["send_as"] == expect
    assert out["body"]
    assert out["cta"] in {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}


def test_determinism():
    m = load_merchant("m_001_drmeera_dentist_delhi")
    args = (load_category("dentists"), m, load_trigger("trg_001_research_digest_dentists"), None)
    assert compose(*args) == compose(*args)


def test_research_digest_is_specific():
    m = load_merchant("m_001_drmeera_dentist_delhi")
    out = compose(load_category("dentists"), m, load_trigger("trg_001_research_digest_dentists"), None)
    # grounded specificity: cites JIDA + the 38% finding + her high-risk cohort size
    assert "JIDA" in out["body"]
    assert "38%" in out["body"]
    assert "124" in out["body"]
