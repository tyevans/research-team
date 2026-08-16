import { describe, expect, it } from 'vitest'

import { decodeFrame } from './event-stream.ts'

const frame = (payload: unknown) => decodeFrame(JSON.stringify(payload))

/** Three channels ride one connection, and only one of them is the durable log.
 *
 * Getting this wrong is not a rendering bug: an approval frame mistaken for a
 * log entry inserts a phantom row, and a log frame mistaken for anything else
 * loses an event. */
describe('decodeFrame', () => {
  it('reads an ordinary log frame', () => {
    const decoded = frame({
      session_id: 's1',
      index: 12,
      type: 'FileWritten',
      occurred_at: '2026-01-01T00:00:00Z',
      summary: '/a.md',
      path: '/a.md',
    })
    expect(decoded).toMatchObject({
      kind: 'log',
      sessionId: 's1',
      entry: { index: 12, type: 'FileWritten', path: '/a.md' },
    })
  })

  it('reads an approval request as an approval, not as a log entry', () => {
    const decoded = frame({
      type: 'ApprovalRequested',
      id: 'a1',
      session_id: 's1',
      tool_name: 'fetch',
      args: { url: 'https://example.com' },
    })
    expect(decoded?.kind).toBe('approvalRequested')
  })

  it('reads a settlement, which carries only the two ids', () => {
    expect(frame({ type: 'ApprovalSettled', id: 'a1', session_id: 's1' })).toEqual({
      kind: 'approvalSettled',
      sessionId: 's1',
      approvalId: 'a1',
    })
  })

  it('reads provisional activity as its own channel', () => {
    const decoded = frame({
      type: 'TurnActivity',
      session_id: 's1',
      message_id: 'm1',
      kind: 'delta',
      text: 'thinking…',
    })
    expect(decoded).toMatchObject({ kind: 'activity', entry: { messageId: 'm1' } })
  })

  it('routes an extraction frame without decoding it', () => {
    // It has no index, so before it had a case of its own it fell through to
    // the log branch and was dropped for being unplaceable — the pane would
    // never have received a frame. The payload rides through unmapped: the
    // per-project store folds it, and only that store knows which project is
    // on screen.
    const decoded = frame({ type: 'Extraction', project_id: 'p1', source_id: 'notes' })
    expect(decoded).toMatchObject({ kind: 'extraction' })
  })

  it('reads a seeding frame, decoded, addressed by project', () => {
    // Unlike extraction, this frame's wire shape already is its full domain
    // model -- `SeedingActivity` hands back one flat frame, not a note to
    // fold -- so it is decoded here rather than routed raw.
    const decoded = frame({
      type: 'Seeding',
      project_id: 'p1',
      run_id: 'r1',
      status: 'running',
    })
    expect(decoded).toMatchObject({
      kind: 'seeding',
      projectId: 'p1',
      run: { runId: 'r1', status: 'running', subject: null },
    })
  })

  it('reads a dispatch frame, decoded, addressed by project', () => {
    // Like seeding: `DispatchQueue` hands back one flat frame that already is
    // the domain model, so it is decoded here rather than routed raw. Without
    // this case the frame falls through to the log branch, fails `logFrameDto`
    // and is dropped with no error at all -- the failure mode the `Extraction`
    // case above carries its own comment about.
    const decoded = frame({
      type: 'Dispatch',
      project_id: 'p1',
      topic_id: 't1',
      dispatch_id: 'd1',
      action: 'understanding',
      status: 'running',
      question: 'How does spacing work?',
    })
    expect(decoded).toMatchObject({
      kind: 'dispatch',
      projectId: 'p1',
      dispatch: {
        dispatchId: 'd1',
        topicId: 't1',
        action: 'understanding',
        status: 'running',
        question: 'How does spacing work?',
        position: null,
        path: null,
      },
    })
  })

  it('reads a dispatch status it does not recognise as running', () => {
    // Guessing toward the state that self-corrects: a row believing itself
    // queued shows a position that will never move, while one believing
    // itself running shows a spinner the next frame corrects.
    expect(
      frame({
        type: 'Dispatch',
        project_id: 'p1',
        topic_id: 't1',
        dispatch_id: 'd1',
        action: 'lesson',
        status: 'deliberating',
      }),
    ).toMatchObject({ kind: 'dispatch', dispatch: { status: 'running', action: 'lesson' } })
  })

  it('reads a topic frame as a topic, not as a log entry', () => {
    // A topic change is a durable log entry, but a topic is not a session:
    // without this case it fell through to the log branch, where its
    // aggregate id would arrive as a `sessionId` and set the tree refetching
    // a session that does not exist -- and, having no `index`, it was in fact
    // dropped outright, which is why a seeded topic only appeared on reload.
    expect(
      frame({
        type: 'Topic',
        topic_id: 't1',
        change: 'TopicOpened',
        occurred_at: '2026-01-01T00:00:00Z',
      }),
    ).toEqual({ kind: 'topic', topicId: 't1', change: 'TopicOpened' })
  })

  it('reads a graph frame as a graph change addressed to its project', () => {
    // The knowledge graph moves inside redstring's own streams, whose
    // aggregate ids are a document's and a tenant's. Without this case the
    // frame fell to the log branch, arrived with a document stream's uuid5
    // under `sessionId`, and -- having no `index` -- was dropped, which is
    // why entities only appeared on a reload.
    expect(
      frame({
        type: 'Graph',
        project_id: 'p1',
        change: 'DocumentExtracted',
        occurred_at: '2026-01-01T00:00:00Z',
      }),
    ).toEqual({ kind: 'graph', projectId: 'p1', change: 'DocumentExtracted' })
  })

  it('reads a corpus frame as its own kind, not as a graph change', () => {
    // Two frames rather than one because a document is stored before it is
    // extracted: an ingest whose extraction fails emits this and no graph
    // frame at all, and the documents pane has to redraw for it.
    expect(
      frame({
        type: 'Corpus',
        project_id: 'p1',
        change: 'CorpusDocumentStored',
        occurred_at: '2026-01-01T00:00:00Z',
      }),
    ).toEqual({ kind: 'corpus', projectId: 'p1', change: 'CorpusDocumentStored' })
  })

  it('reads a media frame as its own kind, not as a session log entry', () => {
    // Without this case the frame fell to the log branch: `feed_event`
    // stamps `index: 0`, `isEventIndex` requires `>= 1`, so the frame was
    // dropped and `MediaProposalPane` polled every 3s instead while a
    // proposal sat in `accepted`.
    expect(
      frame({
        type: 'Media',
        project_id: 'p1',
        change: 'MediaProposalAccepted',
        occurred_at: '2026-01-01T00:00:00Z',
      }),
    ).toEqual({ kind: 'media', projectId: 'p1', change: 'MediaProposalAccepted' })
  })

  it('reads a project frame as its own kind, not as a session log entry', () => {
    // The course page's rail redraws off these. Without this case the frame
    // fell to the log branch, arrived with the project's UUID under
    // `sessionId`, and -- having no `index` -- was dropped, which is why an
    // advanced stage only showed up on a reload.
    expect(
      frame({
        type: 'Project',
        project_id: 'p1',
        change: 'ProjectStageAdvanced',
        decision: 'approve_with_edits',
        occurred_at: '2026-01-01T00:00:00Z',
      }),
    ).toEqual({
      kind: 'project',
      projectId: 'p1',
      change: 'ProjectStageAdvanced',
      // What the reviewer decided, not only that a boundary was crossed --
      // the difference between the live update being a notification and
      // being the information.
      decision: 'approve_with_edits',
    })
  })

  it('reads every project event as one kind, told apart by change', () => {
    // `ProjectWorkflowSelected` is what turns the course page from an error into a
    // rail, so a decoder that admitted only `ProjectStageAdvanced` would have fixed
    // the reported symptom and left its sibling invisible.
    expect(
      frame({
        type: 'Project',
        project_id: 'p1',
        change: 'ProjectWorkflowSelected',
        decision: null,
        occurred_at: '2026-01-01T00:00:00Z',
      }),
    ).toEqual({
      kind: 'project',
      projectId: 'p1',
      change: 'ProjectWorkflowSelected',
      decision: null,
    })
  })

  it('reads a project frame from a server that has no decision field', () => {
    // `decision` arrived after the frame did. A server without it must still
    // move the rail rather than fail validation and leave the page stale --
    // the reason `change` is a plain string rather than an enum. Normalised to
    // null so a consumer tests one thing, not two kinds of absence.
    expect(
      frame({
        type: 'Project',
        project_id: 'p1',
        change: 'ProjectStageAdvanced',
        occurred_at: '2026-01-01T00:00:00Z',
      }),
    ).toEqual({ kind: 'project', projectId: 'p1', change: 'ProjectStageAdvanced', decision: null })
  })

  it('drops a log frame with no index rather than guessing a position', () => {
    // Inserting a row at the wrong point is worse than dropping a frame a
    // reconnect will replay correctly.
    expect(
      frame({ session_id: 's1', type: 'FileWritten', occurred_at: '2026-01-01T00:00:00Z' }),
    ).toBeNull()
  })

  it('drops malformed json without taking the connection down', () => {
    expect(decodeFrame('{not json')).toBeNull()
    expect(decodeFrame('')).toBeNull()
  })

  it('drops a frame whose shape does not match its own type', () => {
    expect(frame({ type: 'ApprovalRequested' })).toBeNull()
    expect(frame({ type: 'TurnActivity', session_id: 's1' })).toBeNull()
  })

  it('carries a cancellation flag through, since it is not a failure', () => {
    const decoded = frame({
      session_id: 's1',
      index: 4,
      type: 'TurnFailed',
      occurred_at: '2026-01-01T00:00:00Z',
      cancelled: true,
    })
    expect(decoded).toMatchObject({ entry: { cancelled: true } })
  })
})
