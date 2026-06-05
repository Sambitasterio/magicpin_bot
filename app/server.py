"""Vera Bot HTTP server — the surface the judge harness drives.

Endpoints: /v1/context, /v1/tick, /v1/reply, /v1/healthz, /v1/metadata, /v1/teardown.
Phase 2 implements context store + tick composition + health/metadata. /v1/reply is a minimal
placeholder here and is fleshed out in Phase 3.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from .composer.core import compose
from .composer.reply import handle_turn
from .config import MODEL_FAST
from .store.context_store import VALID_SCOPES, ContextStore
from .store.conversation import ConversationManager

app = FastAPI(title="Vera Bot")
START = time.time()

store = ContextStore()
cm = ConversationManager()
sent_suppressions: set[str] = set()

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


# How far out a festival is still "worth messaging about". Beyond this we hold back (restraint).
FESTIVAL_HORIZON_DAYS = 21


def _worth_sending(trigger: dict, now: Optional[datetime]) -> bool:
    """Lightweight restraint: skip clearly-untimely triggers. Spam is penalized; restraint rewarded."""
    kind = trigger.get("kind", "")
    payload = trigger.get("payload") or {}

    if kind in ("festival_upcoming", "festival"):
        days = payload.get("days_until")
        if isinstance(days, (int, float)) and days > FESTIVAL_HORIZON_DAYS:
            return False
        date = _parse_iso(payload.get("date", ""))
        if days is None and date and now and (date - now).days > FESTIVAL_HORIZON_DAYS:
            return False
    return True


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
        if not _worth_sending(trg, now):
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

    # Highest urgency first, then restraint: at most one outbound per merchant per tick.
    candidates.sort(key=lambda c: c[0], reverse=True)
    selected: list[tuple] = []
    seen_merchants: set[str] = set()
    for cand in candidates:
        mid = cand[2]["merchant_id"]
        if mid in seen_merchants:
            continue
        seen_merchants.add(mid)
        selected.append(cand)
        if len(selected) >= min(MAX_NEW_COMPOSITIONS_PER_TICK, ACTION_CAP):
            break

    # Compose the selected set concurrently so wall-time stays ~one composition, not the sum.
    def _do(cand):
        _, trg, merchant, category, customer, conv_id = cand
        try:
            return cand, compose(category, merchant, trg, customer, model=MODEL_FAST)
        except Exception:
            return cand, None

    results = []
    if selected:
        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            results = list(pool.map(_do, selected))

    # Assemble actions serially (urgency order preserved) and record state.
    actions: list[dict] = []
    for cand, msg in results:
        if not msg or not msg.get("body"):
            continue
        _, trg, merchant, category, customer, conv_id = cand
        actions.append({
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
        })
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

    return {"actions": actions}


@app.post("/v1/reply")
def reply(body: ReplyBody):
    conv = cm.get(body.conversation_id)
    if conv is None:
        # Cold start (replay-style reply with no prior tick). Open lazily if the merchant is known.
        merchant_ctx = store.get("merchant", body.merchant_id or "")
        if not merchant_ctx:
            return {"action": "end", "rationale": "No open conversation and unknown merchant; nothing to continue."}
        conv = cm.open(
            conversation_id=body.conversation_id,
            merchant_id=merchant_ctx["merchant_id"],
            category_slug=merchant_ctx.get("category_slug", ""),
            send_as="merchant_on_behalf" if body.customer_id else "vera",
            trigger_id="",
            customer_id=body.customer_id,
            suppression_key="",
        )
    elif conv.status != "open":
        return {"action": "end", "rationale": "Conversation already closed."}

    conv.add_turn(body.from_role, body.message)
    category = store.get("category", conv.category_slug) or {}
    merchant = store.get("merchant", conv.merchant_id) or {}
    customer = store.get("customer", conv.customer_id) if conv.customer_id else None

    try:
        result, cls = handle_turn(conv, body.message, category, merchant, customer, model=MODEL_FAST)
    except Exception:
        cm.end(conv.conversation_id)
        return {"action": "end", "rationale": "Failed to compose a reply; closing safely."}

    # Opt-out / hostile -> also suppress the originating trigger so tick won't re-engage.
    if cls in ("opt_out", "hostile") and conv.suppression_key:
        sent_suppressions.add(conv.suppression_key)
    return result


@app.post("/v1/teardown")
def teardown():
    store.clear()
    sent_suppressions.clear()
    cm.clear()
    return {"ok": True, "wiped": True}
