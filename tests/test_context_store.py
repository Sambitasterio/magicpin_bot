"""Unit tests for the versioned, idempotent context store."""
from app.store.context_store import ContextStore


def test_put_and_get():
    s = ContextStore()
    assert s.put("merchant", "m1", 1, {"x": 1}) == ("accepted", 1)
    assert s.get("merchant", "m1") == {"x": 1}


def test_idempotent_same_version_is_stale():
    s = ContextStore()
    s.put("merchant", "m1", 1, {"v": 1})
    assert s.put("merchant", "m1", 1, {"v": 1}) == ("stale", 1)


def test_higher_version_replaces():
    s = ContextStore()
    s.put("merchant", "m1", 1, {"v": 1})
    assert s.put("merchant", "m1", 2, {"v": 2}) == ("accepted", 2)
    assert s.get("merchant", "m1") == {"v": 2}


def test_lower_version_rejected():
    s = ContextStore()
    s.put("merchant", "m1", 5, {"v": 5})
    assert s.put("merchant", "m1", 3, {"v": 3}) == ("stale", 5)
    assert s.get("merchant", "m1") == {"v": 5}


def test_counts():
    s = ContextStore()
    s.put("category", "c", 1, {})
    s.put("merchant", "m", 1, {})
    s.put("customer", "cu", 1, {})
    assert s.counts() == {"category": 1, "merchant": 1, "customer": 1, "trigger": 0}
