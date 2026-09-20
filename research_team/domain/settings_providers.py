"""Provider credentials and dynamic specification generation.

Decomposes settings.py by extracting dynamic provider credential
specification generation into settings_providers.py.
"""

from __future__ import annotations

import research_team.domain.settings as _settings
from research_team.domain.providers import BY_ID, Credential, Provider
from research_team.domain.settings import (
    RESOLUTION_ORDER,
    SettingError,
    SettingSpec,
    SettingType,
    spec_for,
)

__all__ = [
    "PROVIDER_KEY_GROUP",
    "PROVIDER_KEY_PREFIX",
    "_credential_of",
    "_provider_env_var",
    "dynamic_spec_for",
    "dynamic_specs",
    "provider_key",
    "resolve_spec",
]

#: The prefix under which a provider's credentials are stored. Everything after
#: it is `<provider_id>` and, where the provider declares more than one
#: credential, `.<credential>`.
PROVIDER_KEY_PREFIX = "provider_key"

#: What the UI puts provider credentials under. Its own group rather than
#: "Models", because these are not knobs -- a form renders one row per provider
#: the deployment actually uses, not forty checkboxes.
PROVIDER_KEY_GROUP = "Provider credentials"


def _provider_env_var(provider_id: str, credential: str) -> str:
    """The environment variable a dynamic credential also answers to.

    Synthesised rather than omitted, and the reason is that the environment is
    a *layer*, not a legacy: a dynamic setting with no variable name would be
    the one setting in the system that a container could not configure, and the
    resolver would need a branch for it. `AGENT_PROVIDER_KEY_GROQ_API_KEY` is a
    real variable an operator can export today.

    Not in `ENVIRONMENT_ONLY` and not in `SETTINGS`: it belongs to neither
    population, because it does not exist until a provider id is named. See
    `test_a_dynamic_key_cannot_satisfy_the_registry_scan` for why keeping those
    two populations disjoint is the thing being protected.
    """
    return f"AGENT_{PROVIDER_KEY_PREFIX}_{provider_id}_{credential}".upper()


def provider_key(provider_id: str, credential: str | None = None) -> str:
    """The settings key holding one provider credential.

    Built by this function wherever a key is needed rather than formatted at
    each call site, so `ModelProfile.credential_key` and the HTTP path segment
    are the same string by construction.
    """
    if credential is None:
        return f"{PROVIDER_KEY_PREFIX}.{provider_id}"
    return f"{PROVIDER_KEY_PREFIX}.{provider_id}.{credential}"


def _credential_of(provider: Provider, name: str | None) -> Credential:
    """The named credential, or the provider's only one.

    **The trailing segment is required when a provider declares more than one
    credential, and that is not a formality.** Bedrock declares three -- an
    access key id, a secret access key and a region -- and a key of the form
    `provider_key.bedrock` would have to pick one of them silently. Refusing,
    and naming the three, is the difference between a person storing their
    secret access key and a person storing it under the id's name and spending
    an afternoon on why signing fails.
    """
    if name is None:
        if len(provider.credentials) != 1:
            raise SettingError(
                f"{provider.display_name} declares "
                f"{len(provider.credentials)} credentials "
                f"({', '.join(c.name for c in provider.credentials)}); "
                f"name one, e.g. {provider_key(provider.id, provider.credentials[0].name)}"
            )
        return provider.credentials[0]
    for credential in provider.credentials:
        if credential.name == name:
            return credential
    raise SettingError(
        f"{provider.display_name} has no credential {name!r} "
        f"(it declares {', '.join(c.name for c in provider.credentials)})"
    )


def dynamic_spec_for(key: str) -> SettingSpec:
    """A `SettingSpec` for a provider credential, synthesised from the catalogue.

    **The hole this closes.** `ModelProfile.credential_key` names a secret
    setting; the registry declares four secrets, all of them for this project's
    own endpoints; and the catalogue enumerates fifteen providers. So there was
    nowhere to put a Groq key, and bring-your-own-model could be *described*
    and not *stored*. Nothing bridged the two enumerations.

    A dynamic spec is an ordinary `SettingSpec`. Parsing, scoping, encryption
    and masking are unchanged and unbranched -- everything downstream of here
    already takes a spec and does not care where it came from, which is the
    whole reason this is a constructor rather than a second code path.

    **The provider id is validated against the catalogue, never accepted as
    free text.** It lands in a storage key (`SettingOverrideRow.row_id` hashes
    it) and in a URL segment, and unvalidated input in a storage key is a shape
    this project has been bitten by before -- see the memory note on deriving
    ids rather than letting a model pick them. `UnknownProvider` becomes a
    `SettingError` here so the route answers 422/404 rather than 500.

    Secrecy comes from the *credential*, not from the prefix. Azure's
    `resource`, `deployment` and `api_version`, and Bedrock's `region`, are
    declared `secret=False` in the catalogue and are stored and read back in
    the clear, because a region is not a secret and masking it would make the
    settings page unreadable for the two providers that need the most from it.
    """
    if not key.startswith(f"{PROVIDER_KEY_PREFIX}."):
        raise SettingError(f"no setting named {key!r}")
    parts = key.split(".")
    if len(parts) not in (2, 3) or not parts[1]:
        raise SettingError(
            f"{key!r} is not a provider credential key -- expected "
            f"{PROVIDER_KEY_PREFIX}.<provider>[.<credential>]"
        )
    provider_id = parts[1]
    try:
        provider = BY_ID[provider_id]
    except KeyError as error:
        raise SettingError(
            f"no provider named {provider_id!r}; see the provider catalogue"
        ) from error
    credential = _credential_of(provider, parts[2] if len(parts) == 3 else None)
    return SettingSpec(
        key=provider_key(provider.id, credential.name),
        env_var=_provider_env_var(provider.id, credential.name),
        type=SettingType.STRING,
        default=None,
        label=f"{provider.display_name} — {credential.label}",
        description=(
            f"{credential.label} for {provider.display_name}. "
            + (
                "Stored encrypted; never read back."
                if credential.secret
                else "Not a secret; stored and shown in the clear."
            )
        ),
        scopes=frozenset(RESOLUTION_ORDER),
        group=PROVIDER_KEY_GROUP,
        secret=credential.secret,
        required_when=(
            f"a model profile selects {provider.display_name}" if credential.required else None
        ),
    )


def dynamic_specs() -> tuple[SettingSpec, ...]:
    """Every provider credential the catalogue implies, in catalogue order.

    Bounded and small -- fifteen providers, twenty credentials -- which is
    what makes it reasonable for the schema and the resolved read to carry them
    all rather than only the ones somebody has stored. A settings page has to
    be able to show "not set" for a provider you have not configured yet;
    listing only stored keys would mean the form could never offer the first one.
    """
    return tuple(
        dynamic_spec_for(provider_key(provider.id, credential.name))
        for provider in BY_ID.values()
        for credential in provider.credentials
    )


def resolve_spec(key: str) -> SettingSpec:
    """A declaration for any key, declared or dynamic.

    The one entry point for everything above the domain -- the resolver and the
    routes call this, and `spec_for` stays narrowly about `SETTINGS`. Keeping
    them separate is deliberate: `test_every_environment_variable_config_reads_
    is_declared_or_excused` derives its population from the registry, and a
    lookup that quietly synthesised a spec for anything shaped like a provider
    key would let that test be satisfied by a key nobody declared.
    """
    if key.startswith(f"{PROVIDER_KEY_PREFIX}."):
        return dynamic_spec_for(key)
    return spec_for(key)


for _sym in __all__:
    if not hasattr(_settings, _sym):
        setattr(_settings, _sym, globals()[_sym])
