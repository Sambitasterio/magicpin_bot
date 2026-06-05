"""Single point of LLM access. Swap providers/models here only.

Adds a content-addressed disk cache so identical (model, messages) calls are deterministic and free
to replay (important for re-pushes, the static submission build, and dev iteration).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from openai import OpenAI

from .config import MODEL_FAST, OPENAI_API_KEY, SEED, TEMPERATURE, ROOT

_CACHE_DIR = ROOT / ".cache" / "llm"
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def _cache_key(model: str, messages: list[dict], json_mode: bool) -> str:
    blob = json.dumps(
        {"model": model, "messages": messages, "json": json_mode, "t": TEMPERATURE, "seed": SEED},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def complete(
    messages: list[dict],
    model: str = MODEL_FAST,
    json_mode: bool = True,
    use_cache: bool = True,
    max_tokens: int = 700,
) -> str:
    """Return the assistant message content for a chat completion.

    Deterministic: temperature=0 + fixed seed. Cached on disk by (model, messages, json_mode).
    """
    key = _cache_key(model, messages, json_mode)
    cache_file = _CACHE_DIR / f"{key}.json"
    if use_cache and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))["content"]

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": TEMPERATURE,
        "seed": SEED,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    resp = _get_client().chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""

    if use_cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"content": content}, ensure_ascii=False), encoding="utf-8"
        )
    return content
