"""Adapters for the identity provider: the OIDC client and the user recorder.

Its own package rather than a module under `knowledge/` or `persistence/`,
because the two halves here answer to different owners. `oidc.py` speaks to a
system this project does not run; `recorder.py` writes to a log it does. They
are together because they are the only two pieces that know a Zitadel subject
is a string with meaning, and separating them would put that knowledge in two
packages instead of one.
"""

from research_team.infrastructure.identity.oidc import (
    Claims,
    DiscoveryDocument,
    OidcClient,
    OidcError,
)
from research_team.infrastructure.identity.recorder import EventStoreUserRecorder

__all__ = [
    "Claims",
    "DiscoveryDocument",
    "EventStoreUserRecorder",
    "OidcClient",
    "OidcError",
]
