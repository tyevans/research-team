"""The ask HTTP routes and SSE stream.

Its own module and router, extracted from dialogues.py: asking is one
surface (ephemeral chat and Q&A over the project corpus) with its own
models, streaming formats, and read models.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from research_team.application.ask import (
    AskAnswer,
    AskConversationOpened,
    AskInFlight,
    AskService,
)
from research_team.application.ask_components import answer_document
from research_team.application.components import parse_document
from research_team.application.grading import GradingError, grade
from research_team.application.ports import ActivityDelta, ActivityMessage, ActivityRemark
from research_team.infrastructure.persistence.read_models import AskConversationRunner

__all__ = [
    "AskAttempt",
    "AskDeps",
    "AskRequest",
    "_ask_frame",
    "_conversation_view",
    "ask_router",
]


class AskAttempt(BaseModel):
    """One reader's answer to a component the model wrote into an answer.

    Addressed by `(position, component_id)` rather than by a file path: an ask
    answer has no file, and the turn is what the server re-parses to recover
    the key. `position` is in the body rather than the path for `Attempt`'s
    reason -- one addressing scheme for both attempt routes beats two.

    No `at`. A file can be revised under a learner, which is what `Attempt.at`
    defends against; an `AskTurnRecorded` is a fact about an answer that was
    given and is never rewritten, so there is no second version to grade
    against.
    """

    position: int
    component_id: str
    response: Any = None


class AskRequest(BaseModel):
    """One question on one ephemeral chat.

    `chat_id` is the browser's, not the server's: nothing persists a chat, so
    there is no id for a server to have issued. `ConversationRegistry` checks
    the project it was opened under rather than trusting it.
    """

    chat_id: str
    question: str


@dataclass(frozen=True)
class AskDeps:
    """What the ask routes need from `create_app`'s closure."""

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    service: Any | None = None
    ask: AskService | None = None
    asks: AskConversationRunner | None = None
    turns: Any | None = None
    ask_reader: AskService | None = None

    def __post_init__(self) -> None:
        if self.ask is None and self.ask_reader is not None:
            object.__setattr__(self, "ask", self.ask_reader)


def _ask_frame(note: object) -> str | None:
    """One SSE `data:` line per note, or `None` for a note with nothing to draw.

    `message` mirrors ActivityMessage's fields so the browser reuses the
    parsing it already has for the session activity feed.
    """
    if isinstance(note, AskConversationOpened):
        # The first frame of every ask. Without it the browser holds only
        # its own `chat_id`, which is not what the conversation is stored
        # under and never reaches storage at all -- so the history routes
        # below would list conversations the page that produced them could
        # not identify.
        body: dict[str, Any] = {
            "type": "conversation",
            "conversation_id": str(note.conversation_id),
        }
    elif isinstance(note, ActivityDelta):
        body = {
            "type": "delta",
            "message_id": note.message_id,
            "text": note.text,
        }
    elif isinstance(note, ActivityMessage):
        body = {
            "type": "message",
            "message_id": note.message_id,
            "kind": note.kind,
            "payload": note.payload,
            "is_error": note.is_error,
        }
    elif isinstance(note, AskAnswer):
        body = {
            "type": "answer",
            "text": note.text,
            "position": note.position,
            # Parsed here rather than in the browser for the four reasons
            # `application/components.py` opens with, of which the second
            # binds hardest: withholding is only real if the projection
            # happens before the bytes leave. `text` travels beside it
            # anyway (see the design's section 5) -- that is honesty about
            # the strength of the property, not a reason to skip it.
            "blocks": answer_document(note.text)["blocks"],
            "citations": [
                {"kind": citation.kind, "id": citation.id} for citation in note.citations
            ],
        }
    elif isinstance(note, ActivityRemark):
        # Carried, not flattened, and this branch is the whole of B117.
        # The `else` below used to swallow a remark into an assistant
        # message with an empty `payload`, so the page drew a blank bubble
        # mid-answer and dropped the one thing a remark is: its text. A
        # remark has no `message_id` by design (see `ActivityRemark`), so
        # it travels with an empty one and `kind: "remark"` -- which is
        # exactly what `_socratic_frame` already sends, so the browser's
        # activity fold needs one schema rather than two.
        body = {
            "type": "message",
            "message_id": "",
            "kind": "remark",
            "payload": {"text": note.text},
            "is_error": False,
        }
    else:
        # Anything added later, and deliberately nothing rather than an
        # empty bubble: a frame the page cannot render still occupies a row
        # in the transcript, which is worse than a note that is missing.
        # Both `yield` sites below skip a `None`. Same trade, and the same
        # reasoning, as `_socratic_frame`'s final branch.
        return None
    return f"data: {json.dumps(body)}\n\n"


def _conversation_view(row: Any) -> dict[str, Any]:
    """One conversation, without its turns -- what a history list needs.

    `conversationId` is the id the ask stream announced in its first frame
    (`AskConversationOpened`), deliberately the same string: a list whose
    ids did not match what the page was told would let a reader open every
    past conversation except the one they are in.
    """
    return {
        "conversationId": str(row.id),
        "projectId": str(row.project_id),
        "openedAt": row.opened_at.isoformat(),
        "firstQuestion": row.first_question,
        "turnCount": row.turn_count,
    }


def ask_router(deps: AskDeps) -> APIRouter:
    """The Ask routes, ready for `app.include_router`."""
    router = APIRouter()

    async def _check_project(project_id: UUID) -> None:
        if deps.service is not None and deps.require_project is not None:
            await deps.require_project(project_id)

    @router.post("/api/projects/{project_id}/ask")
    async def ask_project(project_id: UUID, body: AskRequest):
        if deps.ask is None:
            raise HTTPException(status_code=503, detail="asking is not configured")
        # Guarded because `create_app` takes every dependency separately and the
        # ask route tests pass `service=None`; without the guard they would fail
        # on the check rather than on what they are about. The cost of skipping
        # it there is that "unknown project" is only enforced in a build that
        # has a session service -- which is every real one.
        await _check_project(project_id)

        notes = deps.ask.ask(
            project_id=project_id, chat_id=body.chat_id, question=body.question
        )
        # `first` and `failed` are the two ways this can come back, and only
        # one of them can still become a status code.
        failed: Exception | None = None
        try:
            first = await anext(notes)
        except AskInFlight as busy:
            # Raised before any streaming begins, so it can still be a status code
            # rather than an error frame the browser has to special-case.
            raise HTTPException(status_code=409, detail=str(busy)) from busy
        except StopAsyncIteration:
            first = None
        except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
            # An executor that fails before its first note -- the ordinary
            # shape of a model that is simply unreachable. A 500 here would be
            # honest but useless to a page that has already opened an
            # EventSource, so it is reported as the same error frame a failure
            # halfway through would produce, and the page needs one path.
            first, failed = None, failure

        async def stream():
            try:
                if failed is not None:
                    raise failed
                if first is not None:
                    frame = _ask_frame(first)
                    if frame is not None:
                        yield frame
                async for note in notes:
                    frame = _ask_frame(note)
                    if frame is not None:
                        yield frame
            except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
                # A stream that simply stops looks identical to a slow model, so a
                # failure is reported in-band before the connection closes.
                yield f"data: {json.dumps({'type': 'error', 'detail': str(failure)})}\n\n"
            finally:
                # The only path that cancels the executor task when a reader
                # walks away: `AskService.ask`'s own `finally` runs when this
                # `aclose()` reaches it, and nothing else would ever cancel a
                # model call the reader has stopped waiting for. The cost of
                # forgetting this line is a live model call per abandoned
                # request.
                #
                # When it runs is the part worth knowing, because it is not
                # "on disconnect". Starlette never calls `aclose()` on
                # `body_iterator`: a disconnect either propagates an `OSError`
                # out of `stream_response` or fires the task group's cancel
                # scope, and in both cases *this* generator is left suspended
                # at a `yield` and never resumed. The `finally` therefore runs
                # when CPython finalises the generator -- the async-generator
                # finalization hook schedules `aclose()` once the last
                # reference drops, or `loop.shutdown_asyncgens` does it at
                # shutdown. It does run; it is not guaranteed to run promptly,
                # so an abandoned model call can outlive the request by as long
                # as the last reference does.
                await notes.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.delete("/api/projects/{project_id}/ask/{chat_id}")
    async def forget_ask(project_id: UUID, chat_id: str):
        if deps.ask is None:
            raise HTTPException(status_code=503, detail="asking is not configured")
        # No `_require_project` here, unlike the POST. Forgetting is local to an
        # in-memory registry, costs nothing to run against an id that names no
        # project, and a page tidying up after a project was deleted underneath
        # it should not be answered 404 for doing so.
        deps.ask.forget(chat_id)
        return {"ok": True}

    @router.get("/api/projects/{project_id}/asks")
    async def list_asks(project_id: UUID):
        """Every conversation asked of this project, most recent first.

        **503 when the projection is unwired, not an empty 200** -- the same
        ruling as `read_ontology`, and it matters more here: an empty list is
        the right answer for a project nobody has asked anything, and an ask
        appends whether or not anything follows the log, so a build with no
        runner started is indistinguishable from a quiet project unless the
        route says so.
        """
        if deps.asks is None:
            raise HTTPException(status_code=503, detail="ask history is not configured")
        return [_conversation_view(row) for row in await deps.asks.for_project(project_id)]

    @router.get("/api/projects/{project_id}/asks/{conversation_id}")
    async def read_ask(project_id: UUID, conversation_id: UUID):
        """One conversation, with its turns in the order they were asked.

        404 covers both "no such conversation" and "that conversation belongs
        to another project", and they are deliberately the same answer: the
        second is a guessed id, and telling a caller that an id they cannot
        read does exist is the distinction not worth drawing.
        """
        if deps.asks is None:
            raise HTTPException(status_code=503, detail="ask history is not configured")
        row = await deps.asks.get(conversation_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no conversation {conversation_id} in {project_id}"
            )
        turns = await deps.asks.turns_for(conversation_id)
        return {
            **_conversation_view(row),
            "turns": [
                {
                    "position": turn.position,
                    "question": turn.question,
                    # **No raw `answer` beside `blocks`, and its absence is the
                    # point.** This shipped `"answer": turn.answer` -- the
                    # stored markdown, fences and all -- next to blocks that
                    # correctly withheld `options[].correct`, so every reopened
                    # conversation handed back the answer key to every question
                    # in it. Measured 2026-08-18 by dumping the response body:
                    # `correct: true` was in the bytes while the projection one
                    # key to its right reported it withheld. `question` stays
                    # raw; it is the reader's own words and there is no key in
                    # it. Same shape as `read_dialogue`'s turns, fixed next
                    # door in 95076c9 for the same reason.
                    #
                    # The cost is that a client wanting the prose walks
                    # `blocks` for its markdown entries instead of reading one
                    # string. That is the right cost: a convenience field
                    # re-adding the source is a hole no projection can close.
                    # Nothing consumed it -- grepped `frontend/src` and the
                    # committed console, which reach only this route's
                    # `/attempts` sibling.
                    "blocks": answer_document(turn.answer)["blocks"],
                    "citations": turn.citations,
                    "recordedAt": turn.recorded_at.isoformat(),
                }
                for turn in turns
            ],
        }

    @router.post("/api/projects/{project_id}/asks/{conversation_id}/attempts")
    async def post_ask_attempt(project_id: UUID, conversation_id: UUID, body: AskAttempt):
        """Mark one attempt at a component the model wrote into an answer.

        The key is recovered by re-parsing the stored answer, which is the same
        move the file surface makes with `session.state.files` -- the browser
        holds the learner projection and could not mark this if it tried.

        **Nothing is recorded.** `LearnerProgress` keys on a session and an ask
        is deliberately not one; the design's section 4 gives the three
        reasons and B33 records the identity question this declines to answer
        by accident. The visible cost is that a refresh blanks the widgets.
        """
        if deps.asks is None:
            raise HTTPException(status_code=503, detail="ask history is not configured")
        row = await deps.asks.get(conversation_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no conversation {conversation_id} in {project_id}"
            )
        turns = await deps.asks.turns_for(conversation_id)
        turn = next((t for t in turns if t.position == body.position), None)
        if turn is None:
            raise HTTPException(
                status_code=404,
                detail=f"conversation {conversation_id} has no turn {body.position}",
            )
        # Re-parsed raw, never through `project()`: that call is what strips
        # the key for a browser, and this is the one caller that needs it,
        # server-side, with nothing it returns carrying the block itself.
        document = parse_document(turn.answer, path="")
        component = document.component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"turn {body.position} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return verdict.as_json()

    return router
