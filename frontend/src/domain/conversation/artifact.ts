import { z } from 'zod'

/** A tool's structured second return value, parsed — or `null`.
 *
 * `null` is not an error case. It is the permanent path for every message
 * written before artifacts existed, every tool nobody has converted, and every
 * tool a future contributor adds and forgets. `ToolResult` renders the model's
 * own string there, exactly as the console always has, so the fallback is what
 * most of a real database takes and it has to be as trustworthy as the shapes.
 *
 * Field names stay snake_case, deliberately. `research_team/application/
 * tool_artifacts.py` is the schema; matching it verbatim means a rename on the
 * wire is a one-file change here, and it removes the class of bug where a
 * renderer reads `charCount` off a dict that says `char_count` and draws a bar
 * of width `NaN` without complaining.
 */

/** A nullable that also tolerates the key being absent, normalised to `null`.
 *  Python writes `None`, JSON carries `null`, and a tool not yet taught to fill
 *  a field omits it; all three mean the same thing to a renderer. */
const maybe = <T extends z.ZodTypeAny>(schema: T) => schema.nullish().transform((v) => v ?? null)

const hit = z.object({
  start: z.number(),
  end: z.number(),
  snippet: z.string(),
})

const sourceHits = z.object({
  source_id: z.string(),
  title: maybe(z.string()),
  label: maybe(z.string()),
  char_count: z.number(),
  total: z.number(),
  hits: z.array(hit),
})

const hitList = z.object({
  shape: z.literal('hit_list'),
  version: z.number(),
  pattern: z.string(),
  total: z.number(),
  suppressed: z.number(),
  sources: z.array(sourceHits),
})

const entityRef = z.object({
  entity_id: z.string(),
  name: z.string(),
  entity_type: z.string(),
  relationship_count: z.number(),
})

const entityList = z.object({
  shape: z.literal('entity_list'),
  version: z.number(),
  query: z.string(),
  mode: z.string(),
  entities: z.array(entityRef),
})

const excerpt = z.object({
  shape: z.literal('excerpt'),
  version: z.number(),
  source_id: z.string(),
  title: maybe(z.string()),
  label: maybe(z.string()),
  start: z.number(),
  end: z.number(),
  char_count: z.number(),
  text: z.string(),
  uri: maybe(z.string()),
})

const inventoryItem = z.object({
  item_id: z.string(),
  title: maybe(z.string()),
  label: maybe(z.string()),
  size: z.number(),
  detail: maybe(z.string()),
})

const inventory = z.object({
  shape: z.literal('inventory'),
  version: z.number(),
  kind: z.string(),
  unit: z.string(),
  total: z.number(),
  items: z.array(inventoryItem),
})

const acknowledgement = z.object({
  shape: z.literal('acknowledgement'),
  version: z.number(),
  action: z.string(),
  subject: z.string(),
  detail: maybe(z.string()),
  ok: z.boolean().default(true),
})

const fileChange = z.object({
  shape: z.literal('file_change'),
  version: z.number(),
  path: z.string(),
  added: z.number(),
  removed: z.number(),
  total_lines: z.number(),
  before: maybe(z.string()),
  after: maybe(z.string()),
})

const worker = z.object({
  name: z.string(),
  started_ms: z.number(),
  duration_ms: maybe(z.number()),
  ok: z.boolean().default(true),
})

const delegation = z.object({
  shape: z.literal('delegation'),
  version: z.number(),
  task: z.string(),
  workers: z.array(worker),
})

/** Discriminated on `shape`, so an unrecognised shape matches no member rather
 *  than being coerced into the nearest one. A card drawn from the wrong member
 *  is a plausible-looking lie; `null` is a fallback to the text the model
 *  actually read. */
export const artifactSchema = z.discriminatedUnion('shape', [
  hitList,
  entityList,
  excerpt,
  inventory,
  acknowledgement,
  fileChange,
  delegation,
])

export type Artifact = z.infer<typeof artifactSchema>
export type Shape = Artifact['shape']

export type HitListArtifact = z.infer<typeof hitList>
export type EntityListArtifact = z.infer<typeof entityList>
export type ExcerptArtifact = z.infer<typeof excerpt>
export type InventoryArtifact = z.infer<typeof inventory>
export type AcknowledgementArtifact = z.infer<typeof acknowledgement>
export type FileChangeArtifact = z.infer<typeof fileChange>
export type DelegationArtifact = z.infer<typeof delegation>

export type EntityRef = z.infer<typeof entityRef>
export type SourceHits = z.infer<typeof sourceHits>
export type InventoryItem = z.infer<typeof inventoryItem>
export type Worker = z.infer<typeof worker>

/** The artifact a message carries, or `null` for the three cases that are one
 *  case to the reader: absent, unrecognised, malformed.
 *
 * `safeParse` rather than `parse`, and not for tidiness: a card that throws
 * takes the whole transcript down with it, and the transcript is the one
 * surface a reader would use to find out what went wrong. */
export const artifactOf = (message: { readonly artifact: unknown }): Artifact | null => {
  if (message.artifact === null || message.artifact === undefined) return null
  const parsed = artifactSchema.safeParse(message.artifact)
  return parsed.success ? parsed.data : null
}

/** One glyph per shape, and the same glyph the call carried.
 *
 * The pairing is the point: a reader scrolling sees a call and its result as
 * one mark repeated, which is what lets the machinery blur into a texture
 * rather than reading as seventeen unrelated novelties. */
export const SHAPE_GLYPH: Record<Shape, string> = {
  hit_list: '⌕',
  entity_list: '◇',
  excerpt: '▤',
  inventory: '▦',
  acknowledgement: '✓',
  file_change: '±',
  delegation: '⑂',
}
