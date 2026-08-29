import type {
  AcknowledgementArtifact,
  DelegationArtifact,
  EntityListArtifact,
  ExcerptArtifact,
  FileChangeArtifact,
  HitListArtifact,
  InventoryArtifact,
} from '@domain/conversation/artifact.ts'
import type { Message } from '@domain/conversation/message.ts'

/** Artifacts as the wire carries them, for the renderer tests.
 *
 * **These are hand-written literals and that is a known limit of every test
 * that uses them.** A literal fixture cannot see a tool that never populates
 * its artifact — the co-mention channel shipped fully unit-tested from both
 * sides and produced nothing for a whole feature for exactly that reason. The
 * test that closes it is `test_every_shape_is_produced_by_a_real_tool_call`,
 * on the Python side, which drives the real tools over real stores. These
 * fixtures test the drawing, and only the drawing.
 *
 * They are snake_case because the wire is, and because a fixture written in
 * the shape the renderer *wishes* it received is a fixture that agrees with a
 * mapping nobody wrote. */

export const toolMessage = (artifact: unknown, content = '19 match(es) for /magic/'): Message => ({
  role: 'tool',
  content,
  toolCalls: [],
  isError: false,
  name: 'search_sources',
  artifact,
})

export const hitList: HitListArtifact = {
  shape: 'hit_list',
  version: 1,
  pattern: 'magic',
  total: 19,
  suppressed: 0,
  sources: [
    {
      source_id: 'manuscriptreport-com-types-of-fictional-genres-42e281d8',
      title: 'manuscriptreport.com',
      label: 'types of fictional genres',
      char_count: 25784,
      total: 9,
      hits: [{ start: 1529, end: 1694, snippet: 'Magic Systems: Define the rules of your magic.' }],
    },
    {
      source_id: 'reedsy-com-story-structure',
      title: 'reedsy.com',
      label: 'story structure',
      char_count: 12000,
      total: 5,
      hits: [{ start: 600, end: 640, snippet: 'a soft magic system' }],
    },
  ],
}

export const hitListMessage = toolMessage(hitList)

/** The same card with something behind the cap, so the expander exists to be
 *  measured. Separate from `hitList` rather than folded into it, because the
 *  "no expander when everything is on screen" assertion needs the other. */
export const hitListMessageWithExpander = toolMessage({ ...hitList, suppressed: 4 })

/** Six entities, counts 6, 2, 2, 1, 1 and one unlinked, so a cap of five, the
 *  sort, the rule and the `–` are all exercised by one fixture. */
export const entityList: EntityListArtifact = {
  shape: 'entity_list',
  version: 1,
  query: 'hard magic system',
  mode: 'vector+lexical',
  entities: [
    { entity_id: 'e1', name: 'Magic Systems', entity_type: 'concept', relationship_count: 2 },
    { entity_id: 'e2', name: 'science fiction', entity_type: 'concept', relationship_count: 6 },
    { entity_id: 'e3', name: 'Canvas', entity_type: 'organization', relationship_count: 2 },
    { entity_id: 'e4', name: 'soft magic system', entity_type: 'concept', relationship_count: 1 },
    { entity_id: 'e5', name: 'hard magic system', entity_type: 'concept', relationship_count: 1 },
    { entity_id: 'e6', name: 'magic', entity_type: 'concept', relationship_count: 0 },
  ],
}

/** Ten, all linked, so the expander has a purely-linked remainder to name. */
export const tenEntities: EntityListArtifact = {
  shape: 'entity_list',
  version: 1,
  query: 'magic',
  mode: 'vector',
  entities: Array.from({ length: 10 }, (_, index) => ({
    entity_id: `t${index}`,
    name: index === 0 ? 'science fiction' : `entity ${index}`,
    entity_type: 'concept',
    relationship_count: 10 - index,
  })),
}

export const excerpt: ExcerptArtifact = {
  shape: 'excerpt',
  version: 1,
  source_id: 'manuscriptreport-com-types-of-fictional-genres-42e281d8',
  title: 'manuscriptreport.com',
  label: 'types of fictional genres',
  start: 1529,
  end: 3872,
  char_count: 25784,
  text: 'complete with their own laws of nature, complex magic systems, unique histories.',
  uri: 'https://manuscriptreport.com/genres',
}

export const inventory: InventoryArtifact = {
  shape: 'inventory',
  version: 1,
  kind: 'sources',
  unit: 'characters',
  total: 3,
  items: [
    { item_id: 's1', title: 'reedsy.com', label: 'story structure', size: 12000, detail: null },
    { item_id: 's2', title: 'fredner.org', label: '104z syllabus', size: 4000, detail: null },
    {
      item_id: 's3',
      title: 'tidepooloctopus.com',
      label: 'history of books',
      size: 900,
      detail: null,
    },
  ],
}

export const acknowledgement: AcknowledgementArtifact = {
  shape: 'acknowledgement',
  version: 1,
  action: 'recorded a finding',
  subject: 'hard vs soft magic systems',
  detail: 'topic “worldbuilding”',
  ok: true,
}

export const fileChange: FileChangeArtifact = {
  shape: 'file_change',
  version: 1,
  path: 'notes/magic.md',
  added: 34,
  removed: 9,
  total_lines: 212,
  before: 'the old line',
  after: 'the new line',
}

/** Four workers, the last still running, the third starting after the second
 *  finished — the serialised-fan-out shape the bars exist to make obvious. */
export const delegation: DelegationArtifact = {
  shape: 'delegation',
  version: 1,
  task: 'summarise each source',
  workers: [
    { name: 'worker-a', started_ms: 0, duration_ms: 4000, ok: true },
    { name: 'worker-b', started_ms: 0, duration_ms: 6000, ok: true },
    { name: 'worker-c', started_ms: 6000, duration_ms: 2000, ok: false },
    { name: 'worker-d', started_ms: 8000, duration_ms: null, ok: true },
  ],
}
