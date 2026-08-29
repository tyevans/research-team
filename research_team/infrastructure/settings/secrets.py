"""Encryption at rest for secret settings, behind `SecretBoxPort`.

AES-256-GCM with a random 96-bit nonce per seal, the key derived from
`AGENT_SETTINGS_KEY`. GCM rather than raw AES because a settings row is a thing
an operator can edit with `sqlite3`, and an unauthenticated ciphertext lets a
flipped byte decrypt to a *different plausible key* rather than to a failure.

**The key is an environment variable and stays one.** Storing it in the
settings table would put the key beside the ciphertext, which is the one place
it must not be; that is why `AGENT_SETTINGS_KEY` is in `ENVIRONMENT_ONLY` with
that sentence attached.

What this does not protect against, said plainly rather than left to be
assumed: anyone who can read the process environment can read every stored
secret, and that includes anything running as the same user on the same box.
This is encryption at rest against a stolen database file and a careless
backup, not against a compromised host. A KMS-backed adapter behind the same
port is the upgrade path and is not built.

**No key configured is a supported state**, and it is the state every existing
test and every current deployment is in: `build_secret_box` returns `None`, the
resolver refuses to *write* a secret with a message naming the variable, and
reading falls through to the environment layer exactly as it did before this
branch existed. The alternative -- generating a key and storing it -- would
make a restart that lost the file look like every credential being wrong.
"""

import base64
import hashlib
import logging
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

#: Marks a value this module produced. Without it, a plaintext value written
#: into the column by hand (or by a build that predates encryption) is
#: indistinguishable from ciphertext, and `open` would answer `None` for it
#: rather than saying anything useful.
PREFIX = "aesgcm:"

NONCE_BYTES = 12


def _key_from(material: str) -> bytes:
    """32 bytes from whatever the operator typed.

    SHA-256 over the raw string rather than a KDF with a salt, and the reason
    is that there is nowhere to put a salt that is not the database this key
    protects. `AGENT_SETTINGS_KEY` is expected to be generated
    (`openssl rand -base64 32`), not chosen, so the offline-guessing attack a
    KDF defends against is not the one that applies -- and a KDF whose salt
    ships beside the ciphertext buys nothing over this.
    """
    return hashlib.sha256(material.encode("utf-8")).digest()


class AesGcmSecretBox:
    """`SecretBoxPort` over AES-256-GCM."""

    def __init__(self, key_material: str) -> None:
        if not key_material.strip():
            raise ValueError("AGENT_SETTINGS_KEY is empty")
        self._cipher = AESGCM(_key_from(key_material))

    def seal(self, plaintext: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        blob = nonce + self._cipher.encrypt(nonce, plaintext.encode("utf-8"), None)
        return PREFIX + base64.b64encode(blob).decode("ascii")

    def open(self, ciphertext: str) -> str | None:
        """The plaintext, or `None` when this key cannot read it.

        `None` rather than an exception because the realistic cause is a
        rotated or replaced `AGENT_SETTINGS_KEY`, which makes every stored
        secret unreadable at once -- raising would 500 the settings page
        instead of showing "unreadable" beside the fields it affects. Logged at
        warning so the cause is discoverable, without the ciphertext in the
        line.
        """
        if not ciphertext.startswith(PREFIX):
            logger.warning("a settings row is not sealed by this build; ignoring it")
            return None
        try:
            blob = base64.b64decode(ciphertext.removeprefix(PREFIX), validate=True)
            nonce, body = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
            return self._cipher.decrypt(nonce, body, None).decode("utf-8")
        except (InvalidTag, ValueError, UnicodeDecodeError):
            # Deliberately broad in cause and narrow in type: a wrong key, a
            # truncated row and a non-base64 column all mean the same thing to
            # a caller -- this value is not readable -- and none of them is a
            # bug in this process worth propagating.
            logger.warning(
                "a stored secret could not be decrypted; is AGENT_SETTINGS_KEY right?"
            )
            return None


def build_secret_box() -> AesGcmSecretBox | None:
    """The box, or `None` when no key is configured.

    `None` is not a degraded box: the resolver refuses to write a secret
    without one, naming the variable. A no-op box that stored plaintext would
    be the same shape and would silently make the encryption decorative, which
    is exactly the failure this returns `None` to avoid.
    """
    material = os.getenv("AGENT_SETTINGS_KEY", "").strip()
    if not material:
        return None
    return AesGcmSecretBox(material)
