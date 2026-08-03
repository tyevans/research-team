"""Subagents, as a way of not growing the context in the first place.

The other two strategies treat a context that has already grown. This one
prevents the growth: work is handed to a subagent that starts fresh, and only
its conclusion comes back. Measured on this codebase, a delegated turn recorded
four messages in the parent -- the request, the `task` call, the subagent's
report, and the reply -- while the subagent's own reads and writes stayed out
of the parent's context entirely.

What makes it fit here rather than merely fit: subagents share the backend, so
their file writes are recorded on the same stream as everything else. The
context shrinks; the audit trail does not.

The cost is real and worth stating. A subagent cannot see the conversation, so
its brief has to carry everything it needs, and a parent cannot check its
working -- only its answer and the file events it left behind.
"""

WORKER = {
    "name": "worker",
    "description": (
        "Carries out a self-contained piece of work -- reading, searching, or "
        "writing files -- and reports back only what the caller needs to know. "
        "Delegate when the work would otherwise fill the conversation with tool "
        "output: surveying many files, or a long edit whose details do not "
        "matter afterwards. Give it everything it needs; it cannot see this "
        "conversation."
    ),
    "system_prompt": (
        "You carry out one scoped task in an in-memory filesystem and report "
        "back.\n\n"
        "You cannot see the conversation that led here, so work only from the "
        "instructions you were given. Use the file tools freely -- your reads "
        "and writes cost the caller nothing, which is why the work was sent to "
        "you.\n\n"
        "Reply with the conclusion alone: what you found or changed, with file "
        "paths, in as few words as carry the meaning. Do not narrate the steps "
        "you took. If you could not do it, say so plainly and say why."
    ),
}

DEFAULT_SUBAGENTS = (WORKER,)

DELEGATION_PROMPT = (
    "\n\nWhen a piece of work would fill this conversation with tool output -- "
    "reading many files, or a long mechanical edit -- hand it to the `worker` "
    "subagent with the `task` tool instead of doing it yourself. It starts "
    "without any of this conversation, so tell it everything it needs, and it "
    "returns only its conclusion. Its file changes are recorded the same as "
    "yours."
)
