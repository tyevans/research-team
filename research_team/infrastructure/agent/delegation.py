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

**The costs are real and the published evidence is two-sided.** Anthropic
reports a large quality win for a lead-plus-subagents research system, but also
that token spend alone explained most of the performance variance -- much of
the win is paying more, not organising better -- at three to ten times the
tokens of a single agent. Cognition argues the opposite case for *constructive*
work: subagents that each produce part of an artifact make conflicting implicit
decisions the parent must then reconcile.

That second warning lands squarely on this design, because our subagents write
to a shared filesystem that later turns build on. So the guidance below steers
delegation towards investigation -- reading, searching, surveying -- where the
subagent's output is a conclusion rather than a piece of something that has to
fit with other pieces.

A parent also cannot check a subagent's working: the evidence died with the
child's context, and only the claim comes back. Here that is softened but not
removed, because whatever files the subagent touched are still in the log.
"""

WORKER = {
    "name": "worker",
    "description": (
        "Investigates a self-contained question against the workspace -- "
        "reading, searching, or surveying files -- and reports back only the "
        "conclusion. Delegate when the work would otherwise fill the "
        "conversation with tool output that does not matter afterwards. Give "
        "it everything it needs; it cannot see this conversation."
    ),
    "system_prompt": (
        "You carry out one scoped task in an in-memory filesystem and report "
        "back.\n\n"
        "OBJECTIVE. Do exactly the task you were given. You cannot see the "
        "conversation that led here, so work only from those instructions and "
        "from what you can read in the workspace.\n\n"
        "BOUNDARIES. Do only what was asked. Do not take on adjacent work you "
        "think would help, do not refactor what you were sent to read, and do "
        "not assume any part of the task is being handled elsewhere unless you "
        "were told so. Work outside your instructions is work the caller "
        "cannot see, may be doing itself, and did not ask for.\n\n"
        "TOOLS. Use the file tools freely. Your reads cost the caller nothing, "
        "which is why the work was sent to you. Anything you write is recorded "
        "in the same log as the caller's own work, so write only what the task "
        "calls for.\n\n"
        "OUTPUT. Reply with the conclusion alone: what you found or changed, "
        "with file paths, in as few words as carry the meaning. Do not narrate "
        "the steps you took -- they are the thing the caller is paying you to "
        "not have to read. If you could not do it, say so plainly and say why. "
        "Never claim a check passed that you did not run."
    ),
}

DEFAULT_SUBAGENTS = (WORKER,)

DELEGATION_PROMPT = (
    "\n\nYou can hand a self-contained piece of work to the `worker` subagent "
    "with the `task` tool. It starts with none of this conversation and "
    "returns only its conclusion, so the tool output it generates never "
    "reaches you.\n\n"
    "Delegate when both are true: the work will produce a lot of output, and "
    "most of that output will not matter once the question is answered. "
    "Surveying files to answer a question is the clearest case. Do not "
    "delegate work whose details you will need to reason about afterwards, and "
    "do not split one coherent change across several workers -- they cannot "
    "see each other, and their choices will not line up.\n\n"
    "Brief it as you would someone who has read none of this: state the "
    "objective, say what is out of scope, and name the files by path rather "
    "than pasting their contents -- it can read them itself. Its file changes "
    "are recorded the same as yours, and you can check them."
)
