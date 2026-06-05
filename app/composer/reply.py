"""Multi-turn reply handling: classify the inbound message, then route to a deterministic action
or an LLM-composed reply.

Deterministic control on the high-risk flows (opt-out, auto-reply) keeps the conversation-flow
score reliable; the LLM handles intent transitions, off-topic redirects, and engaged questions.
"""
from __future__ import annotations

import json
from typing import Optional

from ..config import MODEL_FAST
from ..llm import complete
from ..store.conversation import Conversation, normalize
from .prompts import CTA_VALUES

# --- deterministic detectors (order matters: opt-out/hostile beat everything) ---

_OPT_OUT = [
    "not interested", "stop messaging", "stop sending", "stop these", "stop it", "unsubscribe",
    "leave me alone", "don't message", "do not message", "dont message", "remove me", "no thanks",
    "band karo", "mat bhejo", "mujhe nahi chahiye", "nahi chahiye", "block",
]
_HOSTILE = [
    "useless", "bothering me", "why are you bothering", "nonsense", "spam", "rubbish", "stupid",
    "shut up", "waste of time", "fed up", "annoying",
]
_AUTO_REPLY = [
    "thank you for contacting", "thanks for contacting", "thank you for reaching", "our team will",
    "will respond shortly", "will get back to you", "we will get back", "automated assistant",
    "automated message", "this is an automated", "auto-reply", "autoreply", "we have received your",
    "out of office", "currently away", "office hours", "aapki jaankari ke liye", "team tak pahuncha",
    "main ek automated", "dhanyavaad", "shukriya",
]
_ACCEPT = [
    "let's do it", "lets do it", "go ahead", "please do", "yes please", "sounds good", "do it",
    "ok let's", "okay let's", "set it up", "send it", "draft it", "yes do", "yes send", "confirm",
    "haan kar do", "theek hai karo", "kar do", "chalega", "ready", "let's go", "lets go", "proceed",
]
_SHORT_AFFIRM = {"yes", "ok", "okay", "sure", "haan", "han", "yep", "yes.", "ok.", "👍", "done"}

AUTO_REPLY_FLAG = (
    "Looks like an auto-reply 😊 No rush — when you (the owner) see this, just reply YES "
    "and I'll pick up where we left off."
)


def _contains(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def classify(message: str, conv: Conversation) -> str:
    """Return one of: opt_out, hostile, auto_reply, accept, general."""
    t = normalize(message)

    if _contains(t, _OPT_OUT):
        return "opt_out"
    if _contains(t, _HOSTILE):
        return "hostile"

    # Auto-reply: canned phrasing, or the exact same merchant text repeated.
    prior = [normalize(m) for m in conv.merchant_messages()[:-1]]  # exclude the current message
    if _contains(t, _AUTO_REPLY) or (t and t in prior):
        return "auto_reply"

    if t in _SHORT_AFFIRM or _contains(t, _ACCEPT):
        return "accept"
    return "general"


# --- LLM reply composer (for accept / general / off-topic / engaged) ---

REPLY_SYSTEM = """\
You are Vera continuing a LIVE WhatsApp conversation you already started. You are given the same
four contexts as before, the conversation so far, and the latest inbound message. Write the single
best next move.

Decide an action:
- "send": reply now. Provide "body" and "cta".
- "wait": back off for a while (e.g., the person asked for time). Provide "wait_seconds".
- "end": close the conversation gracefully (they're done, satisfied, or clearly not engaging).

Rules:
- INTENT TRANSITION: if the merchant has agreed / committed ("yes", "let's do it", "go ahead"),
  STOP asking qualifying questions. Immediately execute: deliver the concrete next step or a ready
  artifact, with one low-friction confirmation. Never reply to a "yes" with another question.
- OFF-TOPIC / OUT-OF-SCOPE (e.g. GST filing, unrelated favors): politely decline that part in one
  line, then steer back to the original thread. Don't pretend you can do it.
- ENGAGED QUESTION: answer it using ONLY the provided contexts. Do not fabricate numbers, sources,
  offers, or names. If you don't have it, say so briefly.
- KNOW WHEN TO STOP: if they're satisfied or disengaging, choose "end" rather than forcing another turn.
- Keep the established voice (category fit) and language preference. One primary CTA. No URLs.
- NEVER repeat a message you already sent in this conversation; advance it.

Return ONLY JSON:
{"action": "send|wait|end", "body": "<if send>", "cta": "<one of open_ended|binary_yes_no|binary_confirm_cancel|multi_choice_slot|none>", "wait_seconds": <int if wait>, "rationale": "<1-2 sentences>"}
"""


def _build_reply_user(category, merchant, customer, conv: Conversation, latest: str, directive: str) -> str:
    transcript = "\n".join(f"[{t['from']}] {t['body']}" for t in conv.turns)
    audience = (
        "You are writing AS the merchant to their customer (send_as=merchant_on_behalf)."
        if conv.send_as == "merchant_on_behalf"
        else "You are writing to the merchant as Vera (send_as=vera)."
    )
    parts = [
        f"AUDIENCE: {audience}",
        f"DIRECTIVE: {directive}",
        "",
        "CATEGORY:", json.dumps(category, ensure_ascii=False),
        "MERCHANT:", json.dumps(merchant, ensure_ascii=False),
    ]
    if customer:
        parts += ["CUSTOMER:", json.dumps(customer, ensure_ascii=False)]
    parts += [
        "",
        "CONVERSATION SO FAR:", transcript,
        "",
        f"LATEST INBOUND MESSAGE: {latest}",
        "",
        "Decide the next action and return ONLY the JSON object.",
    ]
    return "\n".join(parts)


def _parse(raw: str) -> dict:
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def compose_reply(category, merchant, customer, conv: Conversation, latest: str, directive: str,
                  model: str = MODEL_FAST) -> dict:
    messages = [
        {"role": "system", "content": REPLY_SYSTEM},
        {"role": "user", "content": _build_reply_user(category, merchant, customer, conv, latest, directive)},
    ]
    result = _parse(complete(messages, model=model))
    action = result.get("action")
    if action not in ("send", "wait", "end"):
        action = "send" if result.get("body") else "end"

    # Anti-repetition: if we'd resend an identical body, ask once for a fresh advance.
    if action == "send" and conv.has_said(result.get("body", "")):
        retry = messages + [
            {"role": "assistant", "content": json.dumps(result, ensure_ascii=False)},
            {"role": "user", "content": "You already sent that exact message. Advance the conversation with a different next step. Return ONLY the JSON object."},
        ]
        result = _parse(complete(messages=retry, model=model)) or result
        action = result.get("action", action)

    cta = result.get("cta")
    if action == "send" and cta not in CTA_VALUES:
        cta = "open_ended"

    out = {"action": action, "rationale": (result.get("rationale") or "").strip()}
    if action == "send":
        out["body"] = (result.get("body") or "").strip()
        out["cta"] = cta
    elif action == "wait":
        out["wait_seconds"] = int(result.get("wait_seconds") or 3600)
    return out


def handle_turn(conv: Conversation, message: str, category, merchant, customer,
                model: str = MODEL_FAST) -> tuple[dict, str]:
    """Route one inbound turn to an action. Mutates `conv` (ends it, increments auto-reply count,
    appends bot turns). Returns (action_dict, classification). The inbound turn must already be
    appended to `conv` by the caller. Shared by the server and conversation_handlers.respond.
    """
    cls = classify(message, conv)

    if cls in ("opt_out", "hostile"):
        conv.status = "ended"
        rationale = (
            "Merchant explicitly opted out; closing and suppressing this thread."
            if cls == "opt_out"
            else "Merchant frustration explicit; closing gracefully without further engagement."
        )
        return {"action": "end", "rationale": rationale}, cls

    if cls == "auto_reply":
        conv.auto_reply_count += 1
        n = conv.auto_reply_count
        if n == 1:
            conv.add_turn("bot", AUTO_REPLY_FLAG)
            return ({"action": "send", "body": AUTO_REPLY_FLAG, "cta": "binary_yes_no",
                     "rationale": "Detected an auto-reply; one explicit prompt to flag it for the owner."}, cls)
        if n == 2:
            return ({"action": "wait", "wait_seconds": 86400,
                     "rationale": "Same auto-reply again — owner not at the phone. Backing off 24h."}, cls)
        conv.status = "ended"
        return ({"action": "end",
                 "rationale": "Auto-reply repeated with no real engagement signal; closing."}, cls)

    directive = (
        "The merchant has explicitly agreed/committed. Switch from qualifying to executing NOW: "
        "deliver the concrete next step or ready artifact with one low-friction confirmation."
        if cls == "accept"
        else "Continue the conversation appropriately (answer, redirect off-topic, or close if done)."
    )
    result = compose_reply(category or {}, merchant or {}, customer, conv, message, directive, model=model)
    if result["action"] == "send" and result.get("body"):
        conv.add_turn("bot", result["body"])
    elif result["action"] == "end":
        conv.status = "ended"
    return result, cls
