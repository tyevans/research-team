"""Bounded, expiring, least-recently-used cache for session/conversation registries.

Provides LRU ordering and idle-TTL eviction with project-boundary enforcement.
"""

from collections import OrderedDict
from collections.abc import Callable
from uuid import UUID


class ExpiringLruCache[K, V]:
    """An OrderedDict-backed LRU cache bounded by entry count and idle seconds.

    Eviction is least-recently-used because a bound that trimmed the newest
    would throw away the chat someone is in the middle of.
    """

    def __init__(
        self,
        *,
        now: Callable[[], float],
        limit: int = 64,
        idle_seconds: float = 3_600.0,
        get_used_at: Callable[[V], float],
        get_project_id: Callable[[V], UUID | None] | None = None,
    ) -> None:
        self._now = now
        self._limit = limit
        self._idle_seconds = idle_seconds
        self._get_used_at = get_used_at
        self._get_project_id = get_project_id
        self._held: OrderedDict[K, V] = OrderedDict()

    def __len__(self) -> int:
        return len(self._held)

    def __bool__(self) -> bool:
        """Always true. A cache exists or it does not; it is never absent for being empty.

        Without this, __len__ makes a fresh registry falsy, and every
        `registry or Registry(...)` default -- the obvious way to write
        an optional collaborator -- silently substitutes a private one.
        """
        return True

    def __contains__(self, key: K) -> bool:
        return key in self._held

    def contains(self, key: K, project_id: UUID | None = None) -> bool:
        """Check whether an entry is currently active in memory and unexpired."""
        held = self._held.get(key)
        if held is None:
            return False
        if (
            project_id is not None
            and self._get_project_id is not None
            and self._get_project_id(held) != project_id
        ):
            return False
        return (self._now() - self._get_used_at(held)) <= self._idle_seconds

    def get(
        self,
        key: K,
        project_id: UUID | None = None,
        now: float | None = None,
    ) -> V | None:
        """Retrieve entry if present, matching project_id, and unexpired.

        On miss, project mismatch, or TTL expiry, any stale entry is evicted
        and None is returned.
        On hit, the entry is promoted to the most-recently-used position.
        """
        current_time = self._now() if now is None else now
        held = self._held.get(key)
        if held is None:
            return None
        if (
            project_id is not None
            and self._get_project_id is not None
            and self._get_project_id(held) != project_id
        ):
            self._held.pop(key, None)
            return None
        if (current_time - self._get_used_at(held)) > self._idle_seconds:
            self._held.pop(key, None)
            return None
        self._held.move_to_end(key)
        return held

    def put(self, key: K, value: V) -> None:
        """Insert or update entry, moving it to MRU position and enforcing capacity."""
        self._held[key] = value
        self._held.move_to_end(key)
        while len(self._held) > self._limit:
            self._held.popitem(last=False)

    def drop(self, key: K) -> None:
        """Remove entry if present."""
        self._held.pop(key, None)

    def clear(self) -> None:
        """Evict all cached entries."""
        self._held.clear()

    def evict_idle(self, now: float | None = None) -> int:
        """Explicitly prune all entries that exceeded idle_seconds."""
        current_time = self._now() if now is None else now
        expired = [
            k
            for k, v in self._held.items()
            if (current_time - self._get_used_at(v)) > self._idle_seconds
        ]
        for k in expired:
            self._held.pop(k, None)
        return len(expired)

    def active_keys(self, project_id: UUID | None = None) -> list[K]:
        """List active, non-expired keys currently held in cache."""
        now = self._now()
        return [
            k
            for k, v in self._held.items()
            if (
                (
                    project_id is None
                    or self._get_project_id is None
                    or self._get_project_id(v) == project_id
                )
                and (now - self._get_used_at(v) <= self._idle_seconds)
            )
        ]

    def values(self) -> list[V]:
        """Return a copy of all held values."""
        return list(self._held.values())
