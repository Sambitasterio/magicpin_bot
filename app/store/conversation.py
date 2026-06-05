"""Per-conversation state for multi-turn handling.

A conversation is opened by /v1/tick (the bot's first outbound) and advanced by /v1/reply. We keep
the turn log, the contexts it was grounded on, an auto-reply counter, and the set of bodies we've
already sent (anti-repetition).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


@dataclass
class Conversation:
    conversation_id: str
    merchant_id: str
    category_slug: str
    send_as: str
    trigger_id: str
    customer_id: Optional[str] = None
    suppression_key: str = ""
    status: str = "open"  # open | ended
    auto_reply_count: int = 0
    turns: list[dict] = field(default_factory=list)  # {"from": "bot|merchant|customer", "body": str}
    _bot_bodies: set[str] = field(default_factory=set)

    def add_turn(self, frm: str, body: str) -> None:
        self.turns.append({"from": frm, "body": body})
        if frm == "bot":
            self._bot_bodies.add(normalize(body))

    def has_said(self, body: str) -> bool:
        return normalize(body) in self._bot_bodies

    def merchant_messages(self) -> list[str]:
        return [t["body"] for t in self.turns if t["from"] in ("merchant", "customer")]


class ConversationManager:
    def __init__(self) -> None:
        self._convs: dict[str, Conversation] = {}
        self._lock = threading.Lock()

    def open(self, **kwargs) -> Conversation:
        conv = Conversation(**kwargs)
        with self._lock:
            self._convs[conv.conversation_id] = conv
        return conv

    def get(self, conversation_id: str) -> Optional[Conversation]:
        return self._convs.get(conversation_id)

    def is_open(self, conversation_id: str) -> bool:
        c = self._convs.get(conversation_id)
        return bool(c and c.status == "open")

    def end(self, conversation_id: str) -> None:
        c = self._convs.get(conversation_id)
        if c:
            c.status = "ended"

    def clear(self) -> None:
        with self._lock:
            self._convs.clear()
