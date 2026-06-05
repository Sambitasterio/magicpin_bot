"""Composer core: compose(category, merchant, trigger, customer?) -> ComposedMessage dict.

This is the brain shared by the live server and the static submission build.
"""
from __future__ import annotations

import json
from typing import Optional

from ..config import MODEL_QUALITY
from ..llm import complete
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .validate import validate

# Trigger payload keys that may reference a CATEGORY.digest item by id.
_DIGEST_REF_KEYS = ("top_item_id", "digest_item_id", "alert_id", "top_item")


def _enrich_trigger(trigger: dict, category: dict) -> dict:
    """Resolve any digest-item reference in the trigger payload into the full item, so the model
    sees the verifiable headline/source/numbers without having to cross-reference itself."""
    payload = trigger.get("payload") or {}
    ref_id = next((payload[k] for k in _DIGEST_REF_KEYS if k in payload), None)
    if not ref_id:
        return trigger
    item = next((d for d in (category.get("digest") or []) if d.get("id") == ref_id), None)
    if not item:
        return trigger
    enriched = dict(trigger)
    enriched["resolved_digest_item"] = item
    return enriched


def _template_name(trigger: dict, send_as: str) -> str:
    kind = trigger.get("kind", "generic")
    prefix = "merchant" if send_as == "merchant_on_behalf" else "vera"
    return f"{prefix}_{kind}_v1"


def _template_params(merchant: dict, customer: Optional[dict], body: str) -> list[str]:
    if customer:
        first = (customer.get("identity") or {}).get("name", "there")
    else:
        ident = merchant.get("identity") or {}
        first = ident.get("owner_first_name") or ident.get("name", "there")
    return [first, body]


def _parse(raw: str) -> dict:
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None,
    model: str = MODEL_QUALITY,
) -> dict:
    """Compose the single next WhatsApp message. Returns:
    {body, cta, send_as, suppression_key, rationale, template_name, template_params}.
    """
    send_as = "merchant_on_behalf" if customer else "vera"
    enriched = _enrich_trigger(trigger, category)

    user_prompt = build_user_prompt(category, merchant, enriched, customer, send_as)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    # The user prompt already contains the serialized contexts — reuse it for grounding checks.
    context_text = user_prompt

    raw = complete(messages, model=model)
    result = _parse(raw)
    result["send_as"] = send_as
    errors = validate(result, send_as, context_text)

    # One repair pass: hand the errors back and ask for a corrected object.
    if errors:
        repair_messages = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your previous JSON failed these checks: "
                    + "; ".join(errors)
                    + ". Return a corrected JSON object with the same keys, fixing every issue. "
                    "Keep the message grounded only in the provided contexts."
                ),
            },
        ]
        raw = complete(repair_messages, model=model)
        repaired = _parse(raw)
        repaired["send_as"] = send_as
        if not validate(repaired, send_as, context_text):
            result = repaired
        else:
            # Keep whichever has a non-empty body; mark residual issues in rationale for transparency.
            if repaired.get("body"):
                result = repaired

    body = (result.get("body") or "").strip()
    return {
        "body": body,
        "cta": result.get("cta", "open_ended"),
        "send_as": send_as,
        "suppression_key": trigger.get("suppression_key", ""),
        "rationale": (result.get("rationale") or "").strip(),
        "template_name": _template_name(trigger, send_as),
        "template_params": _template_params(merchant, customer, body),
    }
