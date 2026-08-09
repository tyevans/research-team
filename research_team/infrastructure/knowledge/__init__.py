"""The knowledge graph adapter, and the only package that imports redstring's
domain vocabulary.

One import elsewhere, deliberately narrow: `persistence/event_store.py` takes
`DOCUMENT_CATEGORY` and `CONSOLIDATION_CATEGORY` from `redstring.events.streams`
so the live feed can carry graph changes. Two string constants and no types --
naming the categories rather than knowing what is in them -- which is why it
does not make that module a second knowledge adapter. It says why in its own
docstring.
"""
