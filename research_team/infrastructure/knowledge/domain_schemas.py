"""`resolve_domain`: a configured domain name as something `build_graph` takes.

`build_graph` accepts `str | DomainSchema | AutoDomain | None`, and this
project needs all three arms: `auto` for redstring's classifier, a bundled id
for anyone who sets one, and a `DomainSchema` object for the schema this
project ships in `schemas/`.

**Loaded, not registered, and that is redstring's design rather than a
workaround.** Its guide is explicit -- "no registration step exists" -- and the
registry has no public method to add a single schema to the bundled set. The
alternative would be pointing `DomainSchemaRegistry` at a directory of our own,
which *replaces* the bundled six rather than extending them: we would own a
copy of six upstream YAML files that drift silently on every pre-1.0 minor.
See the dependency note in `CLAUDE.md` for why that is a bad trade here.

The cost of passing an explicit schema is stated where it is paid, in
`config.knowledge_domain`: it gives up per-document classification. This
project's corpus is one subject at a time, so a schema chosen once beats a
classifier call per document -- but it is a real change and it is reversible by
setting `AGENT_KNOWLEDGE_DOMAIN=auto`.
"""

from pathlib import Path

from redstring import (
    AUTO,
    AutoDomain,
    DomainSchema,
    list_available_domains,
    load_schema_from_file,
)

#: The directory holding this project's own schemas.
#:
#: Absolute, via `__file__`, and that is load-bearing rather than tidiness:
#: `load_schema_from_file` resolves a *relative* path against redstring's own
#: bundled schema directory. A relative path here would not fail loudly -- it
#: would look inside `site-packages` for a file that is not there and raise
#: naming a directory nobody here wrote to.
SCHEMA_DIR = Path(__file__).parent / "schemas"

#: The schema this project extracts with by default. See its YAML for why it
#: exists: no bundled schema asks the model for `temporal_expression`, so
#: nothing this project has ever extracted carried a date the timeline could
#: draw.
RESEARCH_CORPUS = "research_corpus"


def _own_schema_ids() -> set[str]:
    """The ids `SCHEMA_DIR` provides, by filename.

    Read from disk rather than listed as a constant so a schema added to the
    directory is usable without a second edit here -- and so the test that
    sweeps the directory cannot pass over a file this function would not find.
    """
    return {path.stem for path in SCHEMA_DIR.glob("*.yaml")}


def resolve_domain(name: str) -> str | DomainSchema | AutoDomain:
    """`name` as the `domain` argument `build_graph` wants.

    Three arms, in the order a reader should think about them:

    * `auto` -- redstring's `ContentClassifier` chooses per document, at the
      cost of one extra model call. What this project used before it owned a
      schema, and still reachable through `AGENT_KNOWLEDGE_DOMAIN`.
    * one of this project's own ids -- loaded from `SCHEMA_DIR` and returned as
      an object.
    * a bundled redstring id -- returned as a `str` for `build_graph` to
      resolve against its own registry.

    The bundled arm is checked against `list_available_domains` rather than
    against a list kept here. Both refuse a typo, but a list here would be a
    copy of a set that changes across a pre-1.0 minor -- wrong at some later
    version while looking authoritative -- and asking redstring is free.

    Raises:
        ValueError: `name` is empty, or names no schema either this project or
            redstring provides. `build_graph` would refuse a bad id too, but it
            refuses *per ingest*, after the document is stored and the first
            chunks are dispatched. Refusing here moves that to composition,
            where a misconfigured deployment is one line in a log rather than
            an ingest that dies partway through.
    """
    if not name:
        raise ValueError("unknown knowledge domain: the configured name is empty")
    if name == "auto":
        return AUTO
    if name in _own_schema_ids():
        # `SchemaLoadError` is left to propagate rather than wrapped. It names
        # the file and the failing field, which is what a typo in a YAML this
        # project owns needs to say; wrapping it in a ValueError here would
        # replace that with a worse message.
        return load_schema_from_file(SCHEMA_DIR / f"{name}.yaml")
    bundled = {summary.domain_id for summary in list_available_domains()}
    if name in bundled:
        return name
    # A path reaching here is the likely mistake worth naming separately:
    # accepting one would make the extraction prompt depend on a file outside
    # the repository, so a graph could not be explained by the checkout that
    # built it.
    hint = "expected an id, not a path" if "/" in name or name.endswith(".yaml") else ""
    raise ValueError(
        f"unknown knowledge domain {name!r}{': ' + hint if hint else ''}. "
        f"This project ships {sorted(_own_schema_ids())}; "
        f"redstring provides {sorted(bundled)}; 'auto' classifies per document."
    )
