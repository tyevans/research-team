/** How a status is spelled for a person, in one place.
 *
 * The rule "underscores are not shown to people" was written three times as
 * `status.replace('_', ' ')`, in two files: the topic list's row and two
 * places in the topic manage panel (now `TopicManagePane`, which calls
 * `statusLabel` twice instead). One domain vocabulary rule, three copies.
 * Stated in the past tense on purpose — this module is what removed them, so
 * a grep of `frontend/src` for that spelling finds none of the three today,
 * and the line numbers this comment used to cite were stale within a slice.
 *
 * All three are also subtly wrong in the same way, which is the argument for
 * moving them rather than merely sharing them: `String.replace` with a string
 * pattern replaces **only the first occurrence**. No status shipped today has
 * two underscores, so the bug is currently invisible — which is exactly the
 * kind of latent defect that surfaces the day somebody adds
 * `awaiting_human_review`. `replaceAll` is the rule they all meant.
 */

/** Statuses whose plain-English form is not just the identifier with its
 *  underscores removed.
 *
 *  Deliberately small, and it earns each entry. A general prettifier that
 *  title-cased or expanded abbreviations would be inventing vocabulary; these
 *  are the two cases where the identifier and the sentence genuinely differ,
 *  and both come from a report rather than from taste. */
const SPELLED: Readonly<Record<string, string>> = {
  // The course report's C-F46: a run that stopped at a gate is waiting for a
  // person, and filing it under the failures is what made a reader treat a
  // normal pause as a fault.
  human_gate: 'needs a person',
  // "Queue empty" describes the machine's view. What the reader wants to know
  // is that there is nothing left to do.
  queue_empty: 'nothing left to do',
}

export const statusLabel = (status: string): string =>
  SPELLED[status] ?? status.replaceAll('_', ' ')

/** The tones a status chip may take.
 *
 * A closed set, so an unknown tone is a type error rather than a chip with no
 * stylesheet rule — the failure mode `DispatchChip` demonstrates today, being
 * a fifth chip implementation with five bespoke status classes that does not
 * use the shared `Chip` at all.
 */
export type StatusTone = 'neutral' | 'live' | 'good' | 'held' | 'bad'

/** Every status this console shows, mapped to the tone it earns.
 *
 * Two rules in here are load-bearing and come from the reports rather than
 * from how the words sound:
 *
 * **Only `queue_empty` earns `good`** (C-F26/C-F27). Six run endings, and five
 * of them are a run that stopped for a reason somebody needs to look at. A
 * green tick on `budget_exhausted` tells a reader the work finished when it
 * ran out of money.
 *
 * **`human_gate` is `held`, not `bad`** (C-F46). It is the system doing what
 * it was told, waiting for a person. Grouping it with the failures is what
 * made a normal pause read as a fault.
 */
const TONES: Readonly<Record<string, StatusTone>> = {
  // topic
  open: 'neutral',
  investigating: 'live',
  answered: 'good',
  not_pursuing: 'neutral',
  superseded: 'neutral',
  // dispatch
  queued: 'neutral',
  running: 'live',
  done: 'good',
  cancelled: 'neutral',
  failed: 'bad',
  // topic flags
  //
  // Not statuses on the wire -- a topic carries `contested` and `isBlocked`
  // as booleans beside its status -- but they are rendered through the same
  // chip, so this is where "how is that word toned" is answered and there
  // should not be a second place. They were absent, so both fell through to
  // the `neutral` default and drew identically to `open`: the story
  // `entity-topic--detail-needing-attention` named two states and showed
  // neither. `bad` rather than `held`, which is the near miss: `held` is the
  // system waiting for a person and doing what it was told, while a blocked
  // topic and two findings that disagree are both something being wrong.
  blocked: 'bad',
  contested: 'bad',
  // run endings
  queue_empty: 'good',
  budget_exhausted: 'bad',
  human_gate: 'held',
  stalled: 'bad',
  error: 'bad',
}

/** `neutral` for anything unrecognised, on purpose.
 *
 * The alternative — throwing, or falling back to `bad` — would mean a backend
 * that grew a status this build has never heard of either crashes a queue or
 * paints it red. Neither is honest. `neutral` says "this is a status, and I
 * have no opinion about it", which is exactly the truth. */
export const statusTone = (status: string): StatusTone => TONES[status] ?? 'neutral'
