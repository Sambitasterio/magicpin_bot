"""End-to-end server tests via FastAPI TestClient (no network).

Mirrors the judge's warmup + a tick cycle from api-call-examples.md. The single tick we exercise
uses the trg_001/m_001 tuple, whose composition is cached from Phase 1, so no tokens are spent.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import DATA_DIR
from app.server import app

client = TestClient(app)


def _push(scope, context_id, payload, version=1):
    return client.post("/v1/context", json={
        "scope": scope, "context_id": context_id, "version": version,
        "payload": payload, "delivered_at": "2026-06-05T00:00:00Z",
    })


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _warmup():
    client.post("/v1/teardown")
    for f in (DATA_DIR / "categories").glob("*.json"):
        _push("category", _load(f)["slug"], _load(f))
    for f in (DATA_DIR / "merchants").glob("*.json"):
        _push("merchant", _load(f)["merchant_id"], _load(f))
    for f in (DATA_DIR / "customers").glob("*.json"):
        _push("customer", _load(f)["customer_id"], _load(f))


def test_warmup_counts():
    _warmup()
    r = client.get("/v1/healthz").json()
    assert r["status"] == "ok"
    assert r["contexts_loaded"] == {"category": 5, "merchant": 50, "customer": 200, "trigger": 0}


def test_metadata_keys():
    r = client.get("/v1/metadata").json()
    for k in ["team_name", "model", "approach", "contact_email", "version", "submitted_at"]:
        assert k in r


def test_idempotency_and_version_bump():
    _warmup()
    mid = "m_001_drmeera_dentist_delhi"
    payload = _load(DATA_DIR / "merchants" / f"{mid}.json")
    # re-push v1 -> stale
    r = _push("merchant", mid, payload, version=1).json()
    assert r["accepted"] is False and r["reason"] == "stale_version"
    # bump v2 -> accepted
    bumped = dict(payload)
    bumped["performance"] = dict(payload["performance"], views=9999)
    r = _push("merchant", mid, bumped, version=2).json()
    assert r["accepted"] is True


def test_invalid_scope():
    r = _push("widget", "x", {}).json()
    assert r["accepted"] is False and r["reason"] == "invalid_scope"


def test_tick_composes_then_suppresses():
    _warmup()
    trg = _load(DATA_DIR / "triggers" / "trg_001_research_digest_dentists.json")
    _push("trigger", trg["id"], trg)

    r1 = client.post("/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": [trg["id"]]}).json()
    assert len(r1["actions"]) == 1
    a = r1["actions"][0]
    assert a["send_as"] == "vera"
    assert a["body"] and a["cta"] in {"open_ended", "binary_yes_no", "binary_confirm_cancel", "multi_choice_slot", "none"}
    assert a["suppression_key"] == trg["suppression_key"]

    # Same trigger next tick -> suppressed (already acted).
    r2 = client.post("/v1/tick", json={"now": "2026-04-26T10:40:00Z", "available_triggers": [trg["id"]]}).json()
    assert r2["actions"] == []


def test_tick_empty_when_nothing_worthwhile():
    _warmup()
    r = client.post("/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": ["nonexistent"]}).json()
    assert r["actions"] == []
