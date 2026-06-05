"""Phase 4 tests: restraint heuristics, latest-version adaptation, and grounded (non-fabricated) output."""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from app.composer.core import compose
from app.composer.prompts import build_user_prompt
from app.composer.validate import validate
from app.dataset import load_category, load_merchant, load_trigger
from app.server import app, store

client = TestClient(app)


def _push(scope, cid, payload, version=1):
    return client.post("/v1/context", json={
        "scope": scope, "context_id": cid, "version": version, "payload": payload,
        "delivered_at": "2026-06-05T00:00:00Z",
    }).json()


def _tick(triggers, now="2026-04-26T10:35:00Z"):
    return client.post("/v1/tick", json={"now": now, "available_triggers": triggers}).json()


# ---------- restraint ----------

def test_restraint_skips_far_off_festival():
    client.post("/v1/teardown")
    _push("category", "salons", load_category("salons"))
    _push("merchant", "m_003_studio11_salon_hyderabad", load_merchant("m_003_studio11_salon_hyderabad"))
    _push("trigger", "trg_006_festival_diwali", load_trigger("trg_006_festival_diwali"))  # 188 days out
    assert _tick(["trg_006_festival_diwali"])["actions"] == []


def test_one_message_per_merchant_per_tick():
    client.post("/v1/teardown")
    _push("category", "dentists", load_category("dentists"))
    _push("merchant", "m_001_drmeera_dentist_delhi", load_merchant("m_001_drmeera_dentist_delhi"))
    _push("trigger", "trg_001_research_digest_dentists", load_trigger("trg_001_research_digest_dentists"))
    _push("trigger", "trg_023_competitor_opened_dentist", load_trigger("trg_023_competitor_opened_dentist"))
    out = _tick(["trg_001_research_digest_dentists", "trg_023_competitor_opened_dentist"])
    assert len(out["actions"]) == 1  # same merchant -> only one outbound this tick


# ---------- adaptation ----------

def test_latest_version_replaces_via_http():
    client.post("/v1/teardown")
    mid = "m_001_drmeera_dentist_delhi"
    m1 = load_merchant(mid)
    _push("merchant", mid, m1, version=1)
    m2 = copy.deepcopy(m1)
    m2["performance"]["views"] = 9999
    assert _push("merchant", mid, m2, version=2)["accepted"] is True
    assert store.version("merchant", mid) == 2
    assert store.get("merchant", mid)["performance"]["views"] == 9999


def test_changed_context_changes_composition():
    cat = load_category("dentists")
    mer = load_merchant("m_002_bharat_dentist_mumbai")
    trg = load_trigger("trg_004_perf_dip_bharat")  # payload: calls -50% vs_baseline 12
    body_a = compose(cat, mer, trg)["body"]

    trg2 = copy.deepcopy(trg)
    trg2["payload"]["vs_baseline"] = 7
    trg2["payload"]["delta_pct"] = -0.65
    body_b = compose(cat, mer, trg2)["body"]

    assert body_a and body_b
    assert body_a != body_b  # not a stale cache — output adapts to the new numbers


# ---------- no fabrication ----------

def test_output_is_grounded():
    cat = load_category("dentists")
    mer = load_merchant("m_002_bharat_dentist_mumbai")
    trg = load_trigger("trg_004_perf_dip_bharat")
    out = compose(cat, mer, trg)
    ctx = build_user_prompt(cat, mer, trg, None, "vera")
    assert validate(out, "vera", ctx) == []  # no URLs, grounded percentages, valid shape
