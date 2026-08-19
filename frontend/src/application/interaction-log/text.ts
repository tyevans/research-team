/** The bound on the two fields of this vocabulary that carry what a user
 *  typed, applied where they are recorded.
 *
 *  Only `SearchPerformed.query_text` and `AskSubmitted.query_text` are on the
 *  content allowlist; everything else the console reports is structure. This
 *  module exists so the bound is written once rather than at each of the two
 *  emission sites.
 */

/** Must match `QUERY_TEXT_MAX_LENGTH` in `research_team/domain/interaction.py`,
 *  which is where the reasoning for the number lives. Duplicated rather than
 *  served, because a console that has to fetch a constant before it can record
 *  anything is a startup dependency on telemetry -- exactly the coupling this
 *  feature is arranged to avoid. Drifting apart costs a per-event reject at
 *  ingest, which is visible in the route's `rejected` count and loses nothing
 *  else. */
export const QUERY_TEXT_MAX_LENGTH = 4_000

/** Truncated here rather than left for the server to reject.
 *
 *  **Truncate, not drop, and the choice is about what the log is for.** The
 *  server bounds the same field, so an untruncated 500,000-character paste
 *  would be rejected per-event -- correct as a backstop, and the wrong
 *  behaviour as the normal path: the sessions where someone pastes a document
 *  into the ask box are exactly the sessions worth studying, and dropping the
 *  event loses the fact that an ask happened at all, which is structure and
 *  not content. A truncated query still supports the one thing the field
 *  exists for, near-duplicate detection, since two prompts sharing 4,000
 *  characters are near-duplicates by any measure this log will apply.
 *
 *  The cost, stated plainly: a stored value can be a prefix of what was typed
 *  with nothing in the row marking it as one. A `truncated` flag was
 *  considered and rejected -- it is a vocabulary change on a log with no
 *  consumer, and the length is recoverable from the value being exactly at
 *  the bound. */
export const boundQueryText = (text: string): string =>
  text.length <= QUERY_TEXT_MAX_LENGTH ? text : text.slice(0, QUERY_TEXT_MAX_LENGTH)
