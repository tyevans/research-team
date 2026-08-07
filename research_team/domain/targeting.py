"""Checking that a command names the aggregate it is executed against.

eventsource 0.12 moved the aggregate id out of `initial_state()` and onto the
command (ADR 0056). That is the right home for it -- the value before any event
is one value for the aggregate *type* -- but it opens a gap this package had no
way to reach before: a creation command now *repeats* an id the aggregate
already knows, so the two can disagree.

They disagree silently. `decide` is a static function and cannot see the
aggregate, and nothing in the library compares the two, so
`Corpus(a).execute(StoreSourceDocument(corpus_id=b, ...))` produces an event
stamped for `b` and appends it to `a`'s stream. The stream is then unreadable
in the exact way event sourcing is supposed to preclude: the fold of `a` sees
an event that says it belongs elsewhere.

Under the old signature the mismatch was unrepresentable -- state took its id
from `initial_state(aggregate_id)`, so it was the aggregate's id by
construction. This mixin restores that guarantee at the one seam where it can
now be broken, rather than leaving it to every call site to get right.
"""

from typing import Any
from uuid import UUID

from eventsource import CommandRejectedError


class ChecksCommandTarget:
    """Rejects a command whose target id is not this aggregate's.

    Mixed in ahead of `DeciderAggregate` so `execute` runs before the decider's.
    Commands that name no target pass straight through: only the creation
    command of each aggregate carries one, every later command being addressed
    by the stream it is executed against.
    """

    #: The command field naming the aggregate. Set per aggregate.
    target_field: str = ""

    aggregate_id: UUID

    def execute(self, command: Any) -> list[Any]:
        target = getattr(command, self.target_field, None)
        if target is not None and target != self.aggregate_id:
            raise CommandRejectedError(
                f"{type(command).__name__} targets {target}, but this "
                f"{type(self).__name__} is {self.aggregate_id}"
            )
        return super().execute(command)  # type: ignore[misc]
