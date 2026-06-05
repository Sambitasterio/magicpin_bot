"""Optional multi-turn handler (tiebreaker capability).

    respond(state, merchant_message) -> dict

`state` is a mutable dict describing the conversation so far:
    {
      "category": {...}, "merchant": {...}, "customer": {...} | None,
      "send_as": "vera" | "merchant_on_behalf",
      "turns": [ {"from": "bot"|"merchant"|"customer", "body": str}, ... ],
      "auto_reply_count": int,        # optional, defaults 0
      "status": "open" | "ended",     # updated in place
      "suppression_key": str,         # optional
    }

Returns one of:
    {"action": "send", "body": ..., "cta": ..., "rationale": ...}
    {"action": "wait", "wait_seconds": int, "rationale": ...}
    {"action": "end", "rationale": ...}

This is the same routing the live server uses (app/composer/reply.handle_turn): deterministic control
on opt-out and auto-reply flows, LLM for intent transitions, off-topic redirects, and engaged questions.
"""
from __future__ import annotations

from app.composer.reply import handle_turn
from app.store.conversation import Conversation


def _conv_from_state(state: dict) -> Conversation:
    conv = Conversation(
        conversation_id=state.get("conversation_id", "conv"),
        merchant_id=(state.get("merchant") or {}).get("merchant_id", "m"),
        category_slug=(state.get("category") or {}).get("slug", ""),
        send_as=state.get("send_as", "vera"),
        trigger_id=state.get("trigger_id", "t"),
        customer_id=(state.get("customer") or {}).get("customer_id") if state.get("customer") else None,
        suppression_key=state.get("suppression_key", ""),
        status=state.get("status", "open"),
        auto_reply_count=state.get("auto_reply_count", 0),
    )
    for t in state.get("turns", []):
        conv.add_turn(t["from"], t["body"])
    return conv


def respond(state: dict, merchant_message: str) -> dict:
    if state.get("status") == "ended":
        return {"action": "end", "rationale": "Conversation already closed."}

    conv = _conv_from_state(state)
    conv.add_turn("merchant" if conv.send_as == "vera" else "customer", merchant_message)

    result, _cls = handle_turn(
        conv, merchant_message, state.get("category"), state.get("merchant"), state.get("customer")
    )

    # Sync mutated state back to the caller.
    state["turns"] = [{"from": t["from"], "body": t["body"]} for t in conv.turns]
    state["auto_reply_count"] = conv.auto_reply_count
    state["status"] = conv.status
    return result
