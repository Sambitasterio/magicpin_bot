"""Post-LLM validation. Returns a list of human-readable errors (empty = valid).

Deterministic hard rules only — these are the things the judge penalizes operationally or that cap
a dimension. Subjective quality is left to the prompt + the model.
"""
from __future__ import annotations

import re

from .prompts import CTA_VALUES

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
# A crude "stacked CTA" smell: multiple distinct reply-X instructions in one message.
_REPLY_TOKEN_RE = re.compile(r"reply\s+(?:'|\")?[A-Za-z0-9]+", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(\d{1,3})\s*%")
# Sources/authorities/data-providers that models love to invent. If named in the body but absent
# from the contexts, it's fabrication.
_INVENTED_SOURCE_RE = re.compile(
    r"\b(CDSCO|magicpin\s+(?:order\s+)?data|platform\s+data|our\s+data|internal\s+data|FDA|WHO|ICMR)\b",
    re.IGNORECASE,
)


def validate(result: dict, expect_send_as: str, context_text: str = "") -> list[str]:
    errors: list[str] = []

    body = (result.get("body") or "").strip()
    if not body:
        errors.append("body is empty")

    cta = result.get("cta")
    if cta not in CTA_VALUES:
        errors.append(f"cta must be one of {CTA_VALUES}, got {cta!r}")

    if result.get("send_as") != expect_send_as:
        errors.append(
            f"send_as must be {expect_send_as!r} for this scope, got {result.get('send_as')!r}"
        )

    if _URL_RE.search(body):
        errors.append("body contains a URL/link (not allowed on WhatsApp templates)")

    if not (result.get("rationale") or "").strip():
        errors.append("rationale is empty")

    # Stacked-CTA guard: more than 2 explicit "reply X" tokens and not a slot-booking flow.
    reply_tokens = _REPLY_TOKEN_RE.findall(body)
    if len(reply_tokens) > 2 and cta != "multi_choice_slot":
        errors.append("multiple stacked CTAs detected (use a single primary CTA)")

    # Grounding: every percentage in the body must trace to a number in the contexts.
    if context_text:
        for pct in _PERCENT_RE.findall(body):
            if pct not in context_text:
                errors.append(
                    f"percentage {pct}% is not in the contexts — remove it or use a grounded figure"
                )
        src = _INVENTED_SOURCE_RE.search(body)
        if src and src.group(0).lower() not in context_text.lower():
            errors.append(
                f"named source '{src.group(0)}' is not in the contexts — do not attribute data to it"
            )

    return errors
