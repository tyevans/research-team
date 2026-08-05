"""Placeholder for the redstring-backed `KnowledgeGraph` port implementation.

The real adapter is built in the next task. This stub exists only so that
`tests/integration/test_neo4j_graph_store.py` -- specified by this task's
brief, which imports it -- can be collected (and then deselected by default
via the `integration` marker) before that implementation lands. Nothing in
this module is wired into composition.py.
"""


class RedstringKnowledge:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("RedstringKnowledge is implemented in a later task")
