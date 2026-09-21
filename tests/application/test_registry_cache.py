"""Tests for the generic ExpiringLruCache."""

from dataclasses import dataclass
from uuid import UUID, uuid4

from research_team.platform.shared.registry_cache import ExpiringLruCache


@dataclass
class Item:
    id: str
    project_id: UUID
    used_at: float
    value: str


def test_cache_lru_capacity_eviction():
    now_val = 100.0
    cache: ExpiringLruCache[str, Item] = ExpiringLruCache(
        now=lambda: now_val,
        limit=2,
        idle_seconds=60.0,
        get_used_at=lambda item: item.used_at,
        get_project_id=lambda item: item.project_id,
    )
    p = uuid4()
    item1 = Item(id="1", project_id=p, used_at=now_val, value="a")
    item2 = Item(id="2", project_id=p, used_at=now_val, value="b")
    item3 = Item(id="3", project_id=p, used_at=now_val, value="c")

    cache.put("1", item1)
    cache.put("2", item2)
    assert len(cache) == 2
    assert "1" in cache
    assert "2" in cache

    # Access item 1 to make it most recently used
    assert cache.get("1", p) is item1

    # Adding item 3 should evict item 2 (oldest LRU), not item 1
    cache.put("3", item3)
    assert len(cache) == 2
    assert "1" in cache
    assert "3" in cache
    assert "2" not in cache


def test_cache_idle_expiry_and_project_boundary():
    now_val = 100.0
    cache: ExpiringLruCache[str, Item] = ExpiringLruCache(
        now=lambda: now_val,
        limit=10,
        idle_seconds=50.0,
        get_used_at=lambda item: item.used_at,
        get_project_id=lambda item: item.project_id,
    )
    p1 = uuid4()
    p2 = uuid4()
    item = Item(id="1", project_id=p1, used_at=100.0, value="x")
    cache.put("1", item)

    # Wrong project yields None and evicts
    assert cache.get("1", p2) is None
    assert "1" not in cache

    # Put back
    cache.put("1", item)
    assert cache.contains("1", p1)
    assert not cache.contains("1", p2)

    # Advance clock past idle seconds
    now_val = 160.0
    assert not cache.contains("1", p1)
    assert cache.get("1", p1) is None
    assert "1" not in cache


def test_cache_evict_idle_clear_and_active_keys():
    now_val = 100.0
    cache: ExpiringLruCache[str, Item] = ExpiringLruCache(
        now=lambda: now_val,
        limit=10,
        idle_seconds=50.0,
        get_used_at=lambda item: item.used_at,
        get_project_id=lambda item: item.project_id,
    )
    p1 = uuid4()
    p2 = uuid4()
    cache.put("1", Item(id="1", project_id=p1, used_at=40.0, value="old"))
    cache.put("2", Item(id="2", project_id=p1, used_at=95.0, value="fresh-1"))
    cache.put("3", Item(id="3", project_id=p2, used_at=90.0, value="fresh-2"))

    assert cache.active_keys() == ["2", "3"]
    assert cache.active_keys(p1) == ["2"]
    assert cache.active_keys(p2) == ["3"]

    # Explicit eviction
    pruned = cache.evict_idle()
    assert pruned == 1
    assert "1" not in cache
    assert len(cache) == 2

    # Drop and clear
    cache.drop("2")
    assert len(cache) == 1
    assert bool(cache)
    cache.clear()
    assert len(cache) == 0
    assert bool(cache)  # Always truthy
