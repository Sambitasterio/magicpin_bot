"""Submission entry point.

    compose(category, merchant, trigger, customer=None) -> dict

Inputs are the dicts loaded from the dataset JSON (CategoryContext, MerchantContext, TriggerContext,
optional CustomerContext). Returns a dict with keys:
    body, cta, send_as, suppression_key, rationale  (+ template_name, template_params).

Deterministic (temperature=0 + fixed seed) and completes in well under 30s per call. The same logic
backs the live HTTP server's /v1/tick — see app/server.py.
"""
from __future__ import annotations

from typing import Optional

from app.composer.core import compose as _compose


def compose(category: dict, merchant: dict, trigger: dict, customer: Optional[dict] = None) -> dict:
    return _compose(category, merchant, trigger, customer)
