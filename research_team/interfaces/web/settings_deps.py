"""Dependencies for settings and provider HTTP routes."""

from dataclasses import dataclass

from research_team.settings.application import (
    ModelProfileStorePort,
    ProviderProbePort,
    SecretBoxPort,
    SettingsStorePort,
)

__all__ = ["SettingsDeps"]


@dataclass(frozen=True)
class SettingsDeps:
    """What the settings routes need. Everything is built in composition.

    `store` and `secrets` are optional because both are: a deployment with no
    settings database still serves the schema and the provider catalogue (which
    are static), and one with no `AGENT_SETTINGS_KEY` still reads and writes
    every non-secret setting. Answering 503 for the whole surface because one
    half is unwired would hide the half that works.
    """

    store: SettingsStorePort | None = None
    secrets: SecretBoxPort | None = None
    probe: ProviderProbePort | None = None
    profiles: ModelProfileStorePort | None = None

    async def close(self) -> None:
        """Release both stores' connections.

        Here rather than as two steps in `Application.close`, because
        `test_every_close_step_has_a_partial_build_resource` resolves a step
        through the `Application(...)` keyword that filled the attribute, and
        `self.settings.store.close` has one component too many to resolve. One
        method on the thing composition already passes as a unit keeps the two
        lists derivable from each other, which is the whole point of that test.

        `getattr` rather than a `close()` on the ports: both are deliberately
        dumb about scopes, keys and strings (see `SettingsStorePort`), and a
        lifecycle method on the Protocol would oblige every test double to grow
        one for a resource it does not hold. The production adapters are the
        only implementations that own a connection, and they are the only ones
        this needs to find.

        This is not decoration. `aiosqlite` starts a **non-daemon** worker
        thread per connection, so one unclosed store keeps `threading._shutdown`
        waiting and the interpreter never exits -- B5 and B100's symptom, and
        measured on this branch: CI's `pytest` job finished the suite in 6m26s
        and then sat for a further 78 minutes before being cancelled, with the
        runner reporting orphan `uv` and `pytest` processes.
        """
        for store in (self.store, self.profiles):
            closer = getattr(store, "close", None)
            if closer is not None:
                await closer()
