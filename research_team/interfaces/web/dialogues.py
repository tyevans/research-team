"""The ask and socratic dialogue HTTP routes.

Its own module and its own router, for `export.py`, `settings.py`, and `catalog.py`'s reason:
`create_app` is five thousand lines of closures over a few dozen optional
collaborators, and extracting these routes eliminates ~750 lines of monolithic
route closures from `app.py`.

The cost of the split is the dependency record below: these routes need
several of `create_app`'s closures (`_require_project`, etc.)
because they already encode what a 404, 422 and 503 mean here.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from eventsource import CommandRejectedError
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

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
from research_team.application.socratic import (
    DialogueConcluded,
    DialogueInFlight,
    SocraticDialogueOpened,
    SocraticDialogueService,
    SocraticPrompt,
    UnknownDialogue,
)
from research_team.application.socratic_components import dialogue_document
from research_team.infrastructure.persistence.read_models import (
    AskConversationRunner,
    SocraticDialogueRow,
    SocraticDialogueRunner,
)
from research_team.interfaces.web.presenters import dialogue_progress_view, item_view


class Attempt(BaseModel):
    """One learner's answer to one component, addressed in the body.

    The component is named in the body rather than in the path because a file
    path contains slashes, and a route of `/files/{path}/components/{id}` would
    make every caller double-encode one to reach the other. Nothing else about
    the shape depends on that.

    `at` grades against the file as it stood at that event rather than at HEAD.
    Without it, an author revising a question would silently re-mark attempts
    made against the version the learner actually read.
    """

    path: str
    component_id: str
    response: Any = None
    at: int | None = None


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


class SocraticStart(BaseModel):
    """A topic to build a dialogue around.

    No id: unlike an ask's `chat_id`, the dialogue's id is minted by the server
    and returned, because it is an aggregate id, a row key and a URL segment --
    the identical hazard as letting a browser or a model pick one.
    """

    # Constrained because an empty topic is not merely useless: it reaches the
    # model as the whole framing instruction, and a framing that comes back
    # unusable surfaces as a 502 -- blaming the provider for a request that was
    # bad here. 422 from pydantic says the true thing at the true cost (one
    # round trip, no model call). `test_an_empty_topic_is_refused_before_the_model`
    # fails on the constraint being dropped.
    topic: str = Field(min_length=1)


class SocraticReply(BaseModel):
    """What the reader said in answer to the outstanding question.

    Named `reply` and not `question`, matching the domain: on this surface the
    system asks and the reader answers, which is the inverse of the ask.
    """

    reply: str


class SocraticAttempt(BaseModel):
    """One reader's answer to a component the dialogue asked.

    Addressed by `(position, component_id)`, matching `AskAttempt`: a dialogue
    turn has no file path, and the turn is what the server re-parses to recover
    the key. No `at` -- a `SocraticTurnRecorded` is never rewritten, so there is
    no second version to grade against.
    """

    position: int
    component_id: str
    response: Any = None


@dataclass(frozen=True)
class DialogueDeps:
    """What the dialogue and ask routes need from `create_app`'s closure.

    A record rather than a long parameter list, matching `ExportDeps`,
    `SettingsDeps`, and `CatalogDeps`. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    service: Any | None = None
    ask: AskService | None = None
    asks: AskConversationRunner | None = None
    socratic: SocraticDialogueService | None = None
    dialogues: SocraticDialogueRunner | None = None
    turns: Any | None = None
    # Aliases for flexibility across callers
    socratic_dialogues: SocraticDialogueRunner | None = None
    socratic_service: SocraticDialogueService | None = None
    ask_reader: AskService | None = None

    def __post_init__(self) -> None:
        if self.dialogues is None and self.socratic_dialogues is not None:
            object.__setattr__(self, "dialogues", self.socratic_dialogues)
        if self.socratic is None and self.socratic_service is not None:
            object.__setattr__(self, "socratic", self.socratic_service)
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


def _socratic_frame(note: object) -> str | None:
    """One SSE `data:` line per note, or `None` for a note with nothing to draw.

    Deliberately its own function rather than a branch inside `_ask_frame`:
    the last frame of a dialogue turn is typed `prompt` and not `answer`,
    because it is a question. A page that reused the ask's handler would
    draw the dialogue's question in the reader's own column -- and it would
    render, which is why this is a separate function with its own test
    (`test_the_last_frame_is_typed_prompt_and_not_answer`, red against a
    copy-paste of `_ask_frame`).
    """
    if isinstance(note, SocraticDialogueOpened):
        body: dict[str, Any] = {
            "type": "dialogue",
            "dialogue_id": str(note.dialogue_id),
            "goal": note.goal,
            "stopping_condition": note.stopping_condition,
            # The question being answered, not the one about to be asked.
            # On a resumed dialogue this is not the opening one, which is
            # why the field is not called `opening_prompt`.
            #
            # Projected rather than raw, and this one is the leak that
            # nearly survived: `pending_prompt` is the NEWEST turn's prompt
            # (see `read_models.py`, where it is written from exactly
            # that), so on a resumed dialogue it is the component-bearing
            # question the reader is looking at -- key and all. Fixing the
            # `prompt` frame alone would have left this shipping the answer
            # to every question a reader had already been asked, the moment
            # they came back to it.
            "pending_blocks": dialogue_document(note.pending_prompt)["blocks"],
        }
    elif isinstance(note, ActivityDelta):
        # **The dialogue's own prose never goes over this stream, and that
        # is the whole of this branch.** `to_activity_delta` carries the
        # main agent's text exactly as the model produced it, so when the
        # model writes an `mcq` the fence streams with `correct: true` in
        # it -- ahead of the `prompt` frame two branches down, which is at
        # pains to withhold precisely that. Measured on 2026-08-17 by
        # `test_no_frame_of_a_streamed_turn_carries_the_answer_key`, which
        # is red with this `return None` removed.
        #
        # Suppressed rather than filtered or buffered. Filtering the fenced
        # region out of a delta means recognising a fence that has not
        # finished arriving -- a half-written ```` ```component: ```` is
        # indistinguishable from prose until its closing line, so the
        # filter's failure mode is shipping the key it exists to hold back.
        # Buffering until a fence closes has the same recogniser inside it
        # and defers every delta behind an unclosed one. Suppression has no
        # recogniser at all, and on this surface a projection is only real
        # if there is nothing beside it.
        #
        # The frame itself survives with an EMPTY `text`, and that is not
        # tidiness. The console plan for this surface
        # (`docs/superpowers/plans/2026-08-17-socratic-dialogue-console.md`,
        # read rather than assumed) already rules that the transcript's
        # question text comes only from `blocks` and that "deltas drive
        # nothing but a composing indicator" -- so the page folds over
        # delta frames for liveness and ignores their text. Dropping the
        # frame outright would take that liveness signal away with the
        # leak; emptying it takes only the leak.
        #
        # The cost, stated plainly: a reader watching a dialogue compose
        # gets a "composing" indicator and then the finished question, with
        # no token-by-token prose. That is what the plan already assumed.
        # It becomes a real cost the day a console wants the prose itself,
        # and the answer then is a projected delta channel, not the raw
        # one.
        body = {"type": "delta", "message_id": note.message_id, "text": ""}
    elif isinstance(note, ActivityMessage):
        if note.kind == "assistant":
            # The same leak by the other route: `to_activity_message`
            # builds `payload` from `message_to_dict` (`messages.py:54`),
            # so an assistant message carries the model's whole answer --
            # fence and key -- in one frame. The same test measures this
            # one; it caught both halves on the first red run.
            #
            # Tool and error messages still stream: they are what a reader
            # watching a slow turn actually sees, and they carry retrieved
            # source rather than the dialogue's own authored components.
            return None
        body = {
            "type": "message",
            "message_id": note.message_id,
            "kind": note.kind,
            "payload": note.payload,
            "is_error": note.is_error,
        }
    elif isinstance(note, SocraticPrompt):
        body = {
            "type": "prompt",
            # **No raw `text` beside `blocks`, and its absence is the
            # point.** This frame carried `"text": note.prompt` until
            # `test_the_answer_key_never_reaches_the_reader` measured what
            # went over the wire: the projection below withholds
            # `options[].correct`, and the raw copy one key to its left
            # shipped the whole fenced block with `correct: true` in it. A
            # page rendering `blocks` looked correct the entire time; the
            # defect was only ever visible in the bytes.
            #
            # The cost is that a client wanting the prose has to walk
            # `blocks` for its `kind: "markdown"` entries rather than
            # reading one string. That is the right cost: on this surface a
            # projection is only real if there is nothing beside it, and a
            # convenience field that re-adds the source is a hole no
            # projection can close.
            #
            # Parsed here rather than in the browser, for the reasons
            # `components.py` opens with -- the second binds hardest:
            # withholding is only real if the projection happens before the
            # bytes leave, and this surface is the one where being told the
            # answer defeats the method rather than merely leaking.
            "blocks": dialogue_document(note.prompt)["blocks"],
            "position": note.position,
            "citations": [{"kind": kind, "id": cited} for kind, cited in note.citations],
            "concluded": note.concluded,
        }
    elif isinstance(note, ActivityRemark):
        # Carried, not flattened. The brief's version emitted an empty
        # `payload` here, which draws an empty assistant bubble on the page
        # and loses the one thing the remark is: its text. A remark has no
        # `message_id` by design (see `ActivityRemark`), so it travels as a
        # message with an empty one and `kind: "remark"` -- Plan 3 can
        # style it apart from a model utterance without a sixth frame type
        # its DTOs would have to learn.
        body = {
            "type": "message",
            "message_id": "",
            "kind": "remark",
            "payload": {"text": note.text},
            "is_error": False,
        }
    else:
        # Anything added later, and deliberately nothing rather than an
        # empty bubble: a frame the page cannot render is worse than no
        # frame, because it occupies a row in the transcript. The caller
        # skips a `None`. Whoever adds a note type adds a branch here, and
        # the cost of forgetting is a note that is silently invisible --
        # which is the trade taken over a visible blank.
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


def _dialogue_view(row: SocraticDialogueRow) -> dict[str, Any]:
    """One dialogue, without its turns -- what a history list needs.

    `row` is annotated, unlike `_conversation_view`'s beside it: a renamed
    column then fails the type checker rather than the request. Nothing
    else here reads a row, so the looser sibling is left alone.

    Carries `goal` and `stoppingCondition` in the *list* view and not only
    in the detail one, deliberately. A reader picking a dialogue back up
    needs to know what it was aiming at, and the topic alone does not say:
    two dialogues about the Nicene settlement can be trying to do entirely
    different things. It is two strings per row on a page that is a cheap
    index, which is the same trade `firstQuestion` makes on the ask list.
    """
    return {
        "dialogueId": str(row.id),
        "projectId": str(row.project_id),
        "topic": row.topic,
        "goal": row.goal,
        "stoppingCondition": row.stopping_condition,
        # Both projected, never raw. `pendingPrompt` used to be
        # `row.pending_prompt`, which `read_models.py` writes from the
        # newest turn's prompt -- so an index page listing a reader's
        # dialogues handed back the answer key to every live question, on a
        # route nobody thought of as a rendering surface.
        # `test_the_answer_key_never_reaches_the_reader` measures the bytes
        # of all three surfaces rather than trusting any of them.
        "openingBlocks": dialogue_document(row.opening_prompt)["blocks"],
        # The question the reader is looking at now, which belongs to no
        # turn -- see `SocraticTurnRecorded`. A view that omitted it would
        # render a transcript ending on the reader's own words with
        # nothing asking them anything.
        "pendingBlocks": dialogue_document(row.pending_prompt)["blocks"],
        "openedAt": row.opened_at.isoformat(),
        "status": row.status,
        "concludedReason": row.concluded_reason,
        "turnCount": row.turn_count,
        "observations": row.observations,
    }


def dialogue_router(deps: DialogueDeps) -> APIRouter:
    """The Ask and Socratic Dialogue routes, ready for `app.include_router`."""
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

    @router.post("/api/projects/{project_id}/dialogues")
    async def start_dialogue(project_id: UUID, body: SocraticStart):
        """Frame a dialogue and return it -- goal, stopping condition and all.

        Not a stream, unlike the reply route: framing produces three strings and
        no activity worth watching, and a page that opened an EventSource for it
        would show a spinner over an empty transcript. The reader's first sight
        of the dialogue is its goal, and that arrives here.

        **It did not, until this route returned more than an id.** For three
        commits this docstring's last sentence was false: the body was
        `{"dialogueId"}` alone, so a freshly framed dialogue drew an empty
        framing block and an empty thread until the reader answered a question
        they could not see. `read_dialogue` below already served all three
        fields; nothing called it after framing.

        Returned here rather than left to a second `GET` by the client, and the
        trade is worth naming. A second call is one more round trip on the one
        path where the browser has nothing at all to draw in between, and it
        gives the store two independent failure modes (a 404 or a 503 on the
        read) for one reader action -- a dialogue that exists but whose framing
        did not arrive is a state nothing on the page can explain. The cost is
        that this route now needs `dialogues` and answers 503 without it, where
        it previously needed only `socratic`. That is honest rather than a
        narrowing: `composition.py` builds the two together (`socratic_service`
        takes `read_model=dialogues`), and a build with no projection cannot
        resume, list, or re-read any dialogue it mints.

        Reading the projection immediately after the write happens to be safe
        today -- `InMemoryEventBus.publish` dispatches synchronously by default
        (`background=False`), so `SocraticDialogueOpened` is projected before
        `begin` returns -- and that is **not** relied on. A miss falls through to
        `caught_up()` and one retry, which is scoped by aggregate type and so
        returns immediately in the common case rather than running its timeout
        against another stream's append (`SocraticDialogueRunner.caught_up` says
        why the scoping matters). The cost of the retry is one wasted `get` on a
        genuinely absent row; the cost of trusting the bus is a route that
        starts 502ing the day anything passes `background=True`.

        A framing the model botched raises `ValueError` out of `parse_framing`
        and becomes a 502: the request was fine and the upstream was not, which
        is a different thing to tell a reader than a 400.
        """
        if deps.socratic is None or deps.dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        await _check_project(project_id)
        try:
            dialogue_id = await deps.socratic.begin(project_id=project_id, topic=body.topic)
        except ValueError as bad_framing:
            raise HTTPException(
                status_code=502, detail=f"the dialogue could not be framed: {bad_framing}"
            ) from bad_framing
        row = await deps.dialogues.get(dialogue_id)
        if row is None:
            await deps.dialogues.caught_up()
            row = await deps.dialogues.get(dialogue_id)
        if row is None:
            # Unreachable through a working projection, and a 502 rather than
            # an assertion because the failure it reports is real and specific:
            # the dialogue was minted and its framing is not readable, which is
            # a half-made thing the client must not be handed as if it were
            # whole. A dropped `@handles` reaches here as a `TimeoutError` out
            # of `caught_up` instead -- see that method for why.
            raise HTTPException(
                status_code=502,
                detail=f"dialogue {dialogue_id} was framed but its projection is not readable",
            )
        return _dialogue_view(row)

    @router.post("/api/projects/{project_id}/dialogues/{dialogue_id}/reply")
    async def reply_to_dialogue(project_id: UUID, dialogue_id: UUID, body: SocraticReply):
        """Answer the outstanding question, and stream the next one.

        The same two-stage shape as `ask_project`, and for the same reason: the
        first note is pulled before the response begins so that the failures
        which can still be a status code -- 404 for an unknown dialogue, 409 for
        one already running or already concluded -- are status codes rather
        than error frames the page has to special-case.

        A concluded dialogue is a 409 rather than a 404, which is a distinction
        this route used to argue was not worth drawing. It was not, while
        nothing could conclude. It is now: a concluded dialogue is the reader's
        *own*, and their whole history is still stored under that id, so
        answering "no dialogue in project" says the opposite of what happened.
        """
        if deps.socratic is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        await _check_project(project_id)

        notes = deps.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply=body.reply
        )
        failed: Exception | None = None
        try:
            first = await anext(notes)
        except DialogueConcluded as finished:
            # 409 and not 404: the dialogue exists and belongs to this reader,
            # and it is in a state that refuses this request. The same status
            # `post_dialogue_attempt` answers for an attempt against a
            # concluded dialogue, so a page has one rule for both.
            #
            # Ordered above `UnknownDialogue` because it is a subclass -- the
            # broader arm would otherwise swallow it and this reads as working.
            # Measured, not reasoned: swapping the two arms turns
            # `test_replying_to_a_concluded_dialogue_says_it_finished_not_that_it_is_missing`
            # back into a 404.
            raise HTTPException(status_code=409, detail=str(finished)) from finished
        except UnknownDialogue as missing:
            # A guessed id and another project's id are both 404 and stay
            # indistinguishable: confirming that an id a caller cannot use does
            # exist tells a prober which ids exist, and that is a distinction
            # not worth drawing.
            raise HTTPException(status_code=404, detail=str(missing)) from missing
        except DialogueInFlight as busy:
            raise HTTPException(status_code=409, detail=str(busy)) from busy
        except StopAsyncIteration:
            first = None
        except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
            first, failed = None, failure

        async def stream():
            try:
                if failed is not None:
                    raise failed
                if first is not None:
                    frame = _socratic_frame(first)
                    if frame is not None:
                        yield frame
                async for note in notes:
                    frame = _socratic_frame(note)
                    if frame is not None:
                        yield frame
            except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
                yield f"data: {json.dumps({'type': 'error', 'detail': str(failure)})}\n\n"
            finally:
                # The only path that cancels the executor task when a reader
                # walks away. See `ask_project`'s `finally` for when this
                # actually runs -- it is generator finalisation, not disconnect.
                await notes.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/projects/{project_id}/dialogues/{dialogue_id}/attempts")
    async def post_dialogue_attempt(
        project_id: UUID, dialogue_id: UUID, body: SocraticAttempt
    ):
        """Mark one attempt at a component the dialogue asked, and remember it.

        **Unlike `post_ask_attempt`, this records.** An ask has no identity to
        record against; a dialogue is one -- a durable id meaning exactly "one
        reader working toward one goal" -- which is the design's §3 and the
        reason this surface can answer a question the ask path was allowed to
        skip.

        What that buys: the attempt is *recorded* against the dialogue id and
        survives a refresh both in storage and on the page.
        `GET .../dialogues/{dialogue_id}/progress` below is what reads it back
        (B114). For three commits it did not exist -- the only progress read
        route was `GET /api/sessions/{session_id}/progress`, which resolves its
        id through `_load(session_id)` and so cannot serve a dialogue id, and
        `progress_for` on the service is in-process only -- so the property this
        route was built for was real in the event log and invisible in the
        browser.

        The key is recovered by re-parsing the stored turn's `prompt`, which is
        the dialogue's utterance -- not `reply`, which is the reader's. Parsed
        raw and never through `project()`: that call is what strips the key for
        a browser, and this is the one caller that needs it.
        """
        if deps.socratic is None or deps.dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await deps.dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        turn = next(
            (
                t
                for t in await deps.dialogues.turns_for(dialogue_id)
                if t.position == body.position
            ),
            None,
        )
        if turn is None:
            raise HTTPException(
                status_code=404,
                detail=f"dialogue {dialogue_id} has no turn {body.position}",
            )
        component = parse_document(turn.prompt, path="").component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"turn {body.position} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        try:
            # `record_attempt` writes `ObserveSocraticProgress` to the
            # transcript, and `socratic_dialogue.decide` refuses EVERY command
            # against a concluded dialogue -- so an attempt posted at one is a
            # `CommandRejectedError`, which is a 500 without this. Unreachable
            # today, because nothing yet writes `SocraticDialogueConcluded`;
            # that is precisely why it is guarded now rather than when
            # concluding lands, since the plan that adds concluding has no
            # reason to look at this route. 409 matches every neighbouring
            # route (`delete_project` at :941 is the shape).
            #
            # `test_an_attempt_at_a_concluded_dialogue_is_a_409` concludes a
            # dialogue directly and posts to it; it is 500 with this `except`
            # removed, which is how it was proved.
            progress = await deps.socratic.record_attempt(
                project_id=project_id,
                dialogue_id=dialogue_id,
                position=body.position,
                component_id=body.component_id,
                component_type=component.type,
                digest=hashlib.sha256(component.raw.encode("utf-8")).hexdigest(),
                response=body.response,
                correct=verdict.correct,
                score=verdict.score,
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return verdict.as_json() | {
            "progress": item_view(progress, f"turn/{body.position}", body.component_id)
        }

    @router.post("/api/projects/{project_id}/dialogues/{dialogue_id}/end")
    async def end_dialogue(project_id: UUID, dialogue_id: UUID):
        """End a dialogue at the reader's request.

        POST and not DELETE: nothing is removed. The dialogue, its turns and
        every marked answer stay where they were and stay readable, which is the
        opposite of what the wrong verb would tell a reader.

        409 for one already concluded, matching `post_dialogue_attempt` and the
        reply route, so the page has one rule for every "this dialogue has
        finished" it can meet. The row read is against the projection, so two
        ends inside one projection lag both reach `socratic.end` -- which is why
        the `CommandRejectedError` arm is what makes a double-click safe, and not
        the row check. `test_ending_a_dialogue_twice_is_refused_rather_than_written_twice`
        is a 500 with that arm removed.

        The project check is the route's because `ConcludeSocraticDialogue`
        carries no project id and `decide` has nothing to compare: without it a
        guessed id ends someone else's dialogue and answers 200 -- measured, by
        deleting the check: `test_ending_a_dialogue_in_another_project_is_a_404`
        goes green-path and the other project's dialogue is concluded.
        """
        if deps.socratic is None or deps.dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await deps.dialogues.get(dialogue_id)
        if row is None:
            # The same `caught_up()` retry `create_dialogue` takes, and for the
            # same reason: `InMemoryEventBus` dispatches synchronously today, so
            # a miss here is impossible today -- but this is the one route a
            # reader can reach a single frame after `start` resolves, and under
            # `background=True` a reader who ends immediately would be told the
            # dialogue does not exist. That is the exact "it exists, it
            # finished, your history is intact" confusion this surface spent a
            # task correcting in the other direction. Costs one projection wait
            # on a genuinely unknown id, which is the 404 path and not hot.
            # `test_ending_a_dialogue_the_projection_has_not_caught_up_to_yet_still_ends_it`
            # fails with this retry removed; the rest of the end tests pass
            # either way, because a synchronous bus never misses.
            await deps.dialogues.caught_up()
            row = await deps.dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        try:
            await deps.socratic.end(project_id=project_id, dialogue_id=dialogue_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "concluded"}

    @router.get("/api/projects/{project_id}/dialogues/{dialogue_id}/progress")
    async def read_dialogue_progress(project_id: UUID, dialogue_id: UUID):
        """Every answer this reader has had marked in this dialogue (B114).

        **The read side of the route above, and the whole argument for this
        surface being its own principal.** An ask discards an attempt; a
        dialogue records one against a durable id. That claim -- "your answers
        survive a refresh" -- was true in storage and false on screen until this
        existed, because nothing could read the recording back.

        `scope: "dialogue"` is a third shape beside `progress_view`'s `"file"`
        and `"session"`, built rather than folded into the shared presenter.
        `dialogue_progress_view` carries the reasoning and the cost; the short
        form is that a dialogue's records are keyed by an *utterance*
        (`turn/{position}`) and a component id is only unique within one, so
        neither existing key fits, and widening a presenter two other surfaces
        depend on so a third can reuse it is how surfaces couple by accident.

        An untouched dialogue answers `{"items": {}}` and not a 404: nobody has
        answered anything yet is a fact about the reader, not about the id. So
        a test that asserts only the status passes against a route reading an
        id it was never given -- `test_a_recorded_attempt_is_readable_back`
        asserts a stored verdict through the body for that reason.

        Ownership is checked the way both neighbours check it, and a dialogue in
        another project is a 404 rather than a 403 for `read_dialogue`'s reason:
        telling a caller that an id they cannot read does exist is the
        distinction not worth drawing.
        """
        if deps.socratic is None or deps.dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await deps.dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        state = await deps.socratic.progress_for(dialogue_id)
        return dialogue_progress_view(state, str(dialogue_id))

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

    @router.get("/api/projects/{project_id}/dialogues")
    async def list_dialogues(project_id: UUID):
        """Every dialogue held with this project, most recent first.

        **503 when the projection is unwired, not an empty 200** -- the same
        ruling `list_asks` makes and for the same reason: a dialogue appends
        whether or not anything follows the log, so a build with no runner
        started is indistinguishable from a project nobody has talked to unless
        the route says so.
        """
        if deps.dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        return [_dialogue_view(row) for row in await deps.dialogues.for_project(project_id)]

    @router.get("/api/projects/{project_id}/dialogues/{dialogue_id}")
    async def read_dialogue(project_id: UUID, dialogue_id: UUID):
        """One dialogue, with its exchanges in the order they happened.

        404 covers both "no such dialogue" and "that dialogue belongs to
        another project", and they are deliberately the same answer, matching
        `read_ask`: the second is a guessed id, and telling a caller that an id
        they cannot read does exist is the distinction not worth drawing.

        A turn's `blocks` are the dialogue's question and `reply` is the
        reader's answer -- the inverse of `read_ask`'s question/answer, because
        this surface runs in the opposite direction. A client that reused the
        ask's turn renderer here would draw every dialogue with the speakers
        swapped, and it would still read as a conversation.

        A turn pairs the reader's answer with the question it *produced*, so
        the transcript's first utterance is `openingBlocks` on the dialogue
        (not `openingPrompt` -- there is no raw prompt key on any of these
        surfaces any more, see `_dialogue_view`) and is on no turn: a client
        rendering only `turns` draws a reader answering something nobody asked.
        """
        if deps.dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await deps.dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        return {
            **_dialogue_view(row),
            "turns": [
                {
                    "position": turn.position,
                    # Projected, and no raw `prompt` beside it -- the same
                    # measurement as `_socratic_frame`'s. A stored turn is
                    # re-read on every resume, so a raw copy here would hand
                    # back the answer key to any reader who refreshed, for
                    # every question they had already been asked. `reply` is
                    # raw and stays raw: it is the reader's own words and there
                    # is no key in it.
                    "blocks": dialogue_document(turn.prompt)["blocks"],
                    "reply": turn.reply,
                    "citations": turn.citations,
                    "recordedAt": turn.recorded_at.isoformat(),
                }
                for turn in await deps.dialogues.turns_for(dialogue_id)
            ],
        }

    return router
