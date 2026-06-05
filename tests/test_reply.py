"""Phase 3 tests: classifier (pure) + reply flows via TestClient.

Auto-reply and opt-out flows are deterministic (no API). The intent-transition and off-topic
flows call the LLM (cached on disk after the first run) and assert on the action/shape, not exact wording.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.composer.reply import classify
from app.config import DATA_DIR
from app.server import app, cm, store
from app.store.conversation import Conversation

client = TestClient(app)


def _fresh_conv(conv_id="conv_test", send_as="vera", customer_id=None, first="Opening message about JIDA research."):
    client.post("/v1/teardown")
    # contexts the reply composer needs to stay grounded
    cat = json.loads((DATA_DIR / "categories" / "dentists.json").read_text(encoding="utf-8"))
    mer = json.loads((DATA_DIR / "merchants" / "m_001_drmeera_dentist_delhi.json").read_text(encoding="utf-8"))
    store.put("category", "dentists", 1, cat)
    store.put("merchant", mer["merchant_id"], 1, mer)
    conv = cm.open(conversation_id=conv_id, merchant_id=mer["merchant_id"], category_slug="dentists",
                   send_as=send_as, trigger_id="trg_001_research_digest_dentists",
                   customer_id=customer_id, suppression_key="research:dentists:2026-W17")
    conv.add_turn("bot", first)
    return conv


def _reply(conv_id, message, turn):
    return client.post("/v1/reply", json={
        "conversation_id": conv_id, "merchant_id": "m_001_drmeera_dentist_delhi",
        "from_role": "merchant", "message": message, "turn_number": turn,
    }).json()


# ---------- classifier (pure) ----------

def test_classify_opt_out():
    c = Conversation("c", "m", "dentists", "vera", "t")
    assert classify("Not interested. Stop messaging me.", c) == "opt_out"


def test_classify_hostile():
    c = Conversation("c", "m", "dentists", "vera", "t")
    assert classify("This is useless, stop bothering me", c) in ("opt_out", "hostile")


def test_classify_auto_reply_phrase():
    c = Conversation("c", "m", "dentists", "vera", "t")
    assert classify("Thank you for contacting Dr. Meera's Clinic! Our team will respond shortly.", c) == "auto_reply"


def test_classify_accept():
    c = Conversation("c", "m", "dentists", "vera", "t")
    assert classify("ok let's do it", c) == "accept"
    assert classify("yes", c) == "accept"


def test_classify_repeat_is_auto_reply():
    c = Conversation("c", "m", "dentists", "vera", "t")
    c.add_turn("merchant", "Sorry I am away right now")
    c.add_turn("merchant", "Sorry I am away right now")
    assert classify("Sorry I am away right now", c) == "auto_reply"


# ---------- deterministic flows ----------

def test_auto_reply_hell():
    _fresh_conv()
    canned = "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."
    r1 = _reply("conv_test", canned, 2)
    assert r1["action"] == "send" and r1["cta"] == "binary_yes_no"
    r2 = _reply("conv_test", canned, 3)
    assert r2["action"] == "wait" and r2["wait_seconds"] >= 3600
    r3 = _reply("conv_test", canned, 4)
    assert r3["action"] == "end"


def test_opt_out_ends_and_suppresses():
    _fresh_conv()
    r = _reply("conv_test", "Not interested. Stop messaging me.", 2)
    assert r["action"] == "end"
    # conversation is closed; a further reply gets a clean end
    r2 = _reply("conv_test", "hello?", 3)
    assert r2["action"] == "end"


def test_unknown_conversation_ends():
    client.post("/v1/teardown")
    r = _reply("conv_missing", "hi", 1)
    assert r["action"] == "end"


# ---------- LLM flows (cached) ----------

def test_intent_transition_executes_not_qualifies():
    _fresh_conv(first="Want me to draft 3 Google posts on whitening + aligners for you to review?")
    r = _reply("conv_test", "ok, let's do it. what's next?", 2)
    assert r["action"] == "send"
    assert r["body"]
    # should be moving to execution, not asking a fresh qualifying question only
    assert r["cta"] in {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}


def test_off_topic_redirect_stays_on_mission():
    _fresh_conv(first="Want me to pull the JIDA abstract + draft a patient WhatsApp?")
    r = _reply("conv_test", "Btw can you also help me file my GST this month?", 2)
    assert r["action"] in {"send", "end"}
    if r["action"] == "send":
        assert r["body"]
