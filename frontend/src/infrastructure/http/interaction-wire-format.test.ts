/** The one artefact the browser and the route are checked against together.
 *
 * B146: `InteractionLogProvider` -> `HttpInteractionSink` -> `POST
 * /api/interactions` -> `interactions.db` was verified by hand and by nothing
 * that runs. Both *ends* were well covered -- twelve cases on the route in
 * `tests/interfaces/test_interaction_routes.py`, the emitter in
 * `interaction-log-provider.test.tsx` -- and the question "does the body this
 * client actually serialises decode into the events that route registers" was
 * asked by nothing. That is CLAUDE.md's one-adapter-port shape: a stub on one
 * side, a unit test on the other, and no test where they meet.
 *
 * The route's own fixture is the reason it could not be caught there.
 * `_envelope` in that file is hand-written Python, so it supplies the very
 * contract it is meant to check -- the CLAUDE.md rule about a fixture seeding
 * through the same call the code under test depends on, one language over.
 *
 * So the seam is a *file*. This test writes it from the real emitter and the
 * real `HttpInteractionSink`, through the real `JSON.stringify` and the real
 * Blob the beacon carries. `tests/interfaces/test_interaction_wire_format.py`
 * reads the same bytes, posts them at the route and asserts a stored row per
 * event. Neither end can move without the other going red: change the
 * serialiser and this test rewrites the file, and the Python test then fails
 * on the shape the route no longer accepts.
 *
 * Why a committed file rather than a generated one: a fixture regenerated in
 * the same run it is checked against proves nothing (it would agree with any
 * serialiser). Committed, a wire change is a diff in a review.
 *
 * What it deliberately is not: a live HTTP test. There is no Python in this
 * process and no Node in that one; a Playwright job driving a real server
 * would cover more and costs a CI job nobody has agreed to. This covers the
 * format, which is the half that was silently unpinned.
 */

import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { expect, it, vi } from 'vitest'

import { createEmitter } from '@application/interaction-log/emitter.ts'
import { INTERACTION_KINDS } from '@presentation/routing/routes.ts'

import { HttpInteractionSink } from './interaction-log-repository.ts'

// From the project root rather than `import.meta.url`: vitest serves this
// module over an http URL, so `fileURLToPath` refuses it.
const FIXTURE = resolve(
  process.cwd(),
  'src/infrastructure/http/interaction-wire-format.fixture.json',
)

const INSTALL = '2b9c0a1e-0000-4000-8000-000000000001'
const BROWSER_SESSION = '2b9c0a1e-0000-4000-8000-000000000002'
const PROJECT = '11111111-1111-1111-1111-111111111111'
const SESSION = '3f2a0000-0000-0000-0000-000000000000'
const REVIEW = '9d5e0000-0000-0000-0000-000000000003'
const TOPIC = '5c110000-0000-0000-0000-000000000004'

/** One payload per kind, with every field the Python dataclass declares.
 *
 * Keyed by kind and checked for completeness against `INTERACTION_KINDS`
 * below, so a kind added to the vocabulary with no entry here fails rather
 * than quietly going unchecked at the route -- which is how a kind ships that
 * the browser can send and the server rejects.
 */
const PAYLOADS: Record<string, Record<string, unknown>> = {
  ViewEntered: { params: { entity_id: 'ent_4a1f' } },
  ViewExited: { dwell_ms: 2300, hidden_ms: 400 },
  AttentionLost: {},
  AttentionRegained: {},
  EntityOpened: { entity_id: 'ent_4a1f', source: 'search' },
  ProjectSwitched: { to_project_id: PROJECT, from_project_id: null },
  ExtractionQueued: { source_id: 'src_9' },
  ExtractionCancelled: { source_id: 'src_9' },
  DispatchRequested: { topic_id: TOPIC, action: 'sweep' },
  SearchPerformed: { query_text: 'ada lovelace', result_count: 3 },
  AskSubmitted: { query_text: 'what changed' },
  ApprovalDecided: {
    decision: 'approved',
    latency_ms: 4200,
    hidden_ms: 0,
    expanded_details: true,
    review_id: REVIEW,
  },
  ActionUndone: { action_kind: 'render', target_id: null },
  ActionRetried: { action_kind: 'render', attempt_number: 2 },
  EmptyResultEncountered: { where: 'search', query_length: 12 },
  RenderErrorRaised: { where: 'console', error_name: 'TypeError', message_length: 31 },
}

/** The body the beacon actually carries, captured off `navigator.sendBeacon`.
 *
 * `sendOnUnload` rather than `send`, because it is the path that hand-rolls
 * the serialisation: `send` delegates to `HttpClient.post`, and the Blob here
 * is the only place this feature writes JSON itself. */
const wireBody = async (): Promise<string> => {
  let captured = ''
  const beacon = vi.fn((_url: string, payload: Blob) => {
    void payload.text().then((text) => {
      captured = text
    })
    return true
  })
  vi.stubGlobal('navigator', { sendBeacon: beacon })

  const http = {
    url: (path: string) => `http://console.test${path}`,
    post: vi.fn(),
  }
  const emitter = createEmitter({
    sink: new HttpInteractionSink(http as never),
    // Fixed, so the fixture is byte-stable: `occurred_at` is derived from it.
    now: () => Date.parse('2026-08-29T09:00:00.000Z'),
    installId: INSTALL,
    browserSessionId: BROWSER_SESSION,
  })

  emitter.setContext({ view: 'project/entity', projectId: PROJECT, sessionId: SESSION })
  for (const kind of INTERACTION_KINDS) emitter.record(kind, PAYLOADS[kind])
  emitter.flushOnUnload()

  // The Blob read is a promise even for an in-memory blob.
  await new Promise((resolve) => setTimeout(resolve, 0))
  vi.unstubAllGlobals()
  return captured
}

it('names a payload for every kind the browser can send', () => {
  /** Without this, adding a kind to `INTERACTION_KINDS` leaves the fixture a
   *  kind short and the Python end never learns the route has to accept it.
   *  Fails at the assertion below rather than at a missing key, so the
   *  message names the kind. */
  expect(Object.keys(PAYLOADS).sort()).toEqual([...INTERACTION_KINDS].sort())
})

it('serialises a batch into the bytes the route is tested against', async () => {
  const body = await wireBody()
  const pretty = `${JSON.stringify(JSON.parse(body), null, 2)}\n`

  if (process.env.UPDATE_WIRE_FIXTURE === '1') {
    writeFileSync(FIXTURE, pretty)
  }

  // Compared as parsed objects rather than as text, so prettier or an editor
  // reflowing the committed file is not a failure. The *bytes* are what
  // Python reads, and JSON is what both ends mean by them.
  expect(JSON.parse(body)).toEqual(JSON.parse(readFileSync(FIXTURE, 'utf8')))
})
