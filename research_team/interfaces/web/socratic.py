"""The Socratic dialogue HTTP routes and SSE stream.

Its own module and router, extracted from dialogues.py: Socratic dialogue is
a multi-turn learning dialogue with persistent transcripts, component grading,
progress tracking, and dialogue framing.
"""

import hashlib
import json
from uuid import UUID

from eventsource import CommandRejectedError
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from research_team.curriculum.application.grading import GradingError, grade
from research_team.dialogue.application.socratic import (
    DialogueConcluded,
    DialogueInFlight,
    UnknownDialogue,
)
from research_team.dialogue.application.socratic_components import dialogue_document
from research_team.interfaces.web.presenters import dialogue_progress_view, item_view
from research_team.interfaces.web.socratic_views import (
    Attempt,
    SocraticAttempt,
    SocraticDeps,
    SocraticReply,
    SocraticStart,
    _dialogue_view,
    _socratic_frame,
)
from research_team.platform.components import parse_document

__all__ = [
    "Attempt",
    "SocraticAttempt",
    "SocraticDeps",
    "SocraticReply",
    "SocraticStart",
    "_dialogue_view",
    "_socratic_frame",
    "socratic_router",
]


def socratic_router(deps: SocraticDeps) -> APIRouter:
    """The Socratic Dialogue routes, ready for `app.include_router`."""
    router = APIRouter()

    async def _check_project(project_id: UUID) -> None:
        if deps.service is not None and deps.require_project is not None:
            await deps.require_project(project_id)

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
