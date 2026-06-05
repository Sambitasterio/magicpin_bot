"""Vera Bot HTTP server — the surface the judge harness drives.

Endpoints: /v1/context, /v1/tick, /v1/reply, /v1/healthz, /v1/metadata, /v1/teardown.
Phase 2 implements context store + tick composition + health/metadata. /v1/reply is a minimal
placeholder here and is fleshed out in Phase 3.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from .composer.core import compose
from .config import MODEL_FAST
from .store.context_store import VALID_SCOPES, ContextStore

app = FastAPI(title="Vera Bot")
START = time.time()

store = ContextStore()
# Lightweight conversation/dedup state (Phase 3 expands this into a ConversationManager).
sent_suppressions: set[str] = set()
conversations: dict[str, dict] = {}

# Per-tick cap on NEW compositions (cached ones are effectively free). Keeps /v1/tick within budget.
MAX_NEW_COMPOSITIONS_PER_TICK = 5
ACTION_CAP = 20

METADATA = {
    "team_name": "Vera Rebuild",
    "team_members": ["Sambit"],
    "model": MODEL_FAST,
    "approach": "single-prompt composer with per-kind framing + grounding validator; stateful tick/reply",
    "contact_email": "sambit.behera8587@gmail.com",
    "version": "0.2.0",
    "submitted_at": "2026-06-05T00:00:00Z",
}


# ---------- helpers ----------

def _parse_iso(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_expired(trigger: dict, now: Optional[datetime]) -> bool:
    if now is None:
        return False
    exp = _parse_iso(trigger.get("expires_at", ""))
    return exp is not None and exp < now


def _conv_id(merchant_id: str, trigger_id: str) -> str:
    return f"conv_{merchant_id}__{trigger_id}"


# ---------- models ----------

class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str | None = None


class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []


class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: str | None = None
    customer_id: str | None = None
    from_role: str
    message: str
    received_at: str | None = None
    turn_number: int = 1


# ---------- endpoints ----------

@app.get("/v1/healthz")
def healthz():
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START),
        "contexts_loaded": store.counts(),
    }


@app.get("/v1/metadata")
def metadata():
    return METADATA


@app.post("/v1/context")
def push_context(body: CtxBody):
    if body.scope not in VALID_SCOPES:
        return {"accepted": False, "reason": "invalid_scope", "details": f"unknown scope {body.scope!r}"}
    status, current = store.put(body.scope, body.context_id, body.version, body.payload)
    if status == "stale":
        return {"accepted": False, "reason": "stale_version", "current_version": current}
    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/v1/tick")
def tick(body: TickBody):
    now = _parse_iso(body.now)

    # Build eligible candidates: resolvable, unsuppressed, unexpired, not already-active conversation.
    candidates: list[tuple[int, dict, dict, dict, Optional[dict], str]] = []
    for trg_id in body.available_triggers:
        trg = store.get("trigger", trg_id)
        if not trg:
            continue
        supp = trg.get("suppression_key", "")
        if supp and supp in sent_suppressions:
            continue
        if _is_expired(trg, now):
            continue
        merchant = store.get("merchant", trg.get("merchant_id", ""))
        if not merchant:
            continue
        category = store.get("category", merchant.get("category_slug", ""))
        if not category:
            continue
        conv_id = _conv_id(merchant["merchant_id"], trg_id)
        if conv_id in conversations:
            continue
        customer = store.get("customer", trg["customer_id"]) if trg.get("customer_id") else None
        candidates.append((int(trg.get("urgency", 1)), trg, merchant, category, customer, conv_id))

    # Highest urgency first; cap new compositions for latency.
    candidates.sort(key=lambda c: c[0], reverse=True)

    actions: list[dict] = []
    for _, trg, merchant, category, customer, conv_id in candidates[:MAX_NEW_COMPOSITIONS_PER_TICK]:
        try:
            msg = compose(category, merchant, trg, customer, model=MODEL_FAST)
        except Exception:
            continue
        if not msg.get("body"):
            continue
        action = {
            "conversation_id": conv_id,
            "merchant_id": merchant["merchant_id"],
            "customer_id": customer["customer_id"] if customer else None,
            "send_as": msg["send_as"],
            "trigger_id": trg["id"],
            "template_name": msg["template_name"],
            "template_params": msg["template_params"],
            "body": msg["body"],
            "cta": msg["cta"],
            "suppression_key": msg["suppression_key"],
            "rationale": msg["rationale"],
        }
        actions.append(action)
        if trg.get("suppression_key"):
            sent_suppressions.add(trg["suppression_key"])
        conversations[conv_id] = {
            "merchant_id": merchant["merchant_id"],
            "customer_id": customer["customer_id"] if customer else None,
            "trigger_id": trg["id"],
            "category_slug": merchant.get("category_slug"),
            "send_as": msg["send_as"],
            "turns": [{"from": "bot", "body": msg["body"]}],
            "status": "open",
        }
        if len(actions) >= ACTION_CAP:
            break

    return {"actions": actions}


@app.post("/v1/reply")
def reply(body: ReplyBody):
    # Phase 3 implements auto-reply detection, intent handoff, graceful exit. Minimal placeholder:
    conv = conversations.get(body.conversation_id)
    if conv is not None:
        conv["turns"].append({"from": body.from_role, "body": body.message})
    return {
        "action": "end",
        "rationale": "Reply handling is implemented in Phase 3; ending conversation for now.",
    }


@app.post("/v1/teardown")
def teardown():
    store.clear()
    sent_suppressions.clear()
    conversations.clear()
    return {"ok": True, "wiped": True}
