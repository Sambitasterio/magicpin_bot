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
from .composer.reply import classify, compose_reply
from .config import MODEL_FAST
from .store.context_store import VALID_SCOPES, ContextStore
from .store.conversation import ConversationManager

app = FastAPI(title="Vera Bot")
START = time.time()

store = ContextStore()
cm = ConversationManager()
sent_suppressions: set[str] = set()

AUTO_REPLY_FLAG = (
    "Looks like an auto-reply 😊 No rush — when you (the owner) see this, just reply YES "
    "and I'll pick up where we left off."
)

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
        if cm.get(conv_id) is not None:
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
        conv = cm.open(
            conversation_id=conv_id,
            merchant_id=merchant["merchant_id"],
            customer_id=customer["customer_id"] if customer else None,
            trigger_id=trg["id"],
            category_slug=merchant.get("category_slug", ""),
            send_as=msg["send_as"],
            suppression_key=msg["suppression_key"],
        )
        conv.add_turn("bot", msg["body"])
        if len(actions) >= ACTION_CAP:
            break

    return {"actions": actions}


@app.post("/v1/reply")
def reply(body: ReplyBody):
    conv = cm.get(body.conversation_id)
    if conv is None or conv.status != "open":
        return {"action": "end", "rationale": "No open conversation for this id."}

    conv.add_turn(body.from_role, body.message)
    cls = classify(body.message, conv)

    # Opt-out / hostile -> end + suppress the originating trigger.
    if cls in ("opt_out", "hostile"):
        cm.end(conv.conversation_id)
        if conv.suppression_key:
            sent_suppressions.add(conv.suppression_key)
        rationale = (
            "Merchant explicitly opted out; closing and suppressing this thread."
            if cls == "opt_out"
            else "Merchant frustration explicit; closing gracefully without further engagement."
        )
        return {"action": "end", "rationale": rationale}

    # Auto-reply -> flag once, then back off, then end.
    if cls == "auto_reply":
        conv.auto_reply_count += 1
        n = conv.auto_reply_count
        if n == 1:
            conv.add_turn("bot", AUTO_REPLY_FLAG)
            return {"action": "send", "body": AUTO_REPLY_FLAG, "cta": "binary_yes_no",
                    "rationale": "Detected an auto-reply; one explicit prompt to flag it for the owner."}
        if n == 2:
            return {"action": "wait", "wait_seconds": 86400,
                    "rationale": "Same auto-reply again — owner not at the phone. Backing off 24h."}
        cm.end(conv.conversation_id)
        return {"action": "end",
                "rationale": "Auto-reply repeated with no real engagement signal; closing."}

    # accept / general -> LLM-composed next move.
    directive = (
        "The merchant has explicitly agreed/committed. Switch from qualifying to executing NOW: "
        "deliver the concrete next step or ready artifact with one low-friction confirmation."
        if cls == "accept"
        else "Continue the conversation appropriately (answer, redirect off-topic, or close if done)."
    )
    category = store.get("category", conv.category_slug) or {}
    merchant = store.get("merchant", conv.merchant_id) or {}
    customer = store.get("customer", conv.customer_id) if conv.customer_id else None

    try:
        result = compose_reply(category, merchant, customer, conv, body.message, directive)
    except Exception:
        cm.end(conv.conversation_id)
        return {"action": "end", "rationale": "Failed to compose a reply; closing safely."}

    if result["action"] == "send" and result.get("body"):
        conv.add_turn("bot", result["body"])
    elif result["action"] == "end":
        cm.end(conv.conversation_id)
    return result


@app.post("/v1/teardown")
def teardown():
    store.clear()
    sent_suppressions.clear()
    cm.clear()
    return {"ok": True, "wiped": True}
