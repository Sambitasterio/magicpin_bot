"""Tests for the submission artifacts: bot.compose shape + conversation_handlers.respond (deterministic flows)."""
from __future__ import annotations

from bot import compose
from conversation_handlers import respond
from app.dataset import load_category, load_merchant, load_trigger


def test_bot_compose_shape():
    m = load_merchant("m_001_drmeera_dentist_delhi")
    out = compose(load_category("dentists"), m, load_trigger("trg_001_research_digest_dentists"))
    for k in ["body", "cta", "send_as", "suppression_key", "rationale"]:
        assert k in out
    assert out["send_as"] == "vera" and out["body"]


def _state(first="Want me to draft 3 whitening posts?"):
    return {
        "category": load_category("dentists"),
        "merchant": load_merchant("m_001_drmeera_dentist_delhi"),
        "customer": None,
        "send_as": "vera",
        "turns": [{"from": "bot", "body": first}],
        "status": "open",
        "suppression_key": "k",
    }


def test_respond_opt_out_ends():
    st = _state()
    r = respond(st, "Not interested, stop messaging me")
    assert r["action"] == "end"
    assert st["status"] == "ended"


def test_respond_auto_reply_flag_then_wait():
    st = _state()
    canned = "Thank you for contacting us! Our team will respond shortly."
    r1 = respond(st, canned)
    assert r1["action"] == "send" and r1["cta"] == "binary_yes_no"
    r2 = respond(st, canned)
    assert r2["action"] == "wait"
    assert st["auto_reply_count"] == 2


def test_respond_on_ended_state():
    st = _state()
    st["status"] = "ended"
    assert respond(st, "hello")["action"] == "end"
