import type { ReactNode } from 'react'

import type { LoggedInteraction } from '@domain/interaction/log.ts'

import { plural } from '../formatting/format.ts'
import { INTERACTION_KINDS, type InteractionKind } from '../routing/routes.ts'
import { durationMs } from './duration.ts'

/** One row of the log, said in English.
 *
 * **A renderer per kind, and the switch below is exhaustive by construction.**
 * The `never` assignment in the default arm is the whole point: a kind added
 * to `INTERACTION_KINDS` and not to this switch is a type error at build time
 * rather than a feed row that renders blank at runtime. Blank is the failure
 * that matters here -- this is the surface whose job is that a broken
 * instrument stops looking like an idle user, and a row with no prose is
 * indistinguishable from a row whose payload was genuinely empty.
 *
 * **Prose rather than the dict.** The raw payload is one disclosure away on
 * every row (`InteractionFeed`), so nothing is hidden; what is bought is that
 * a screenful of the log reads as a sequence of things somebody did. A feed of
 * fifteen JSON objects is a table nobody scans.
 *
 * Every reader below is defensive about its own fields, and that is not
 * paranoia: `payload` is `Record<string, unknown>` because the shape differs
 * per kind, and enumerating fifteen shapes in the domain layer would put the
 * vocabulary in two languages twice over. A field that is missing renders as
 * the part of the sentence it can, never as `undefined`.
 */
export const interactionProse = (event: LoggedInteraction): ReactNode => {
  const { payload, view } = event
  if (!isInteractionKind(event.kind)) {
    // A kind the console's own vocabulary does not hold. Loud rather than
    // blank, because there are exactly two ways to get here and both are worth
    // seeing: the server grew a kind this build does not know about, or a row
    // was written by something that is not the recorder.
    return <em>unrecognised kind — see the payload</em>
  }

  switch (event.kind) {
    case 'ViewEntered':
      return `entered ${view}`
    case 'ViewExited': {
      const hidden = num(payload, 'hidden_ms')
      const left = `left ${view} after ${durationMs(num(payload, 'dwell_ms'))}`
      // Only when there was any: "(0.0s hidden)" on every row is noise, and
      // the number is interesting exactly when it is not zero. Never
      // subtracted from the dwell -- `ViewExited`'s own docstring says the
      // consumer chooses, and this consumer chooses to show both.
      return hidden !== null && hidden > 0 ? `${left} (${durationMs(hidden)} hidden)` : left
    }
    case 'AttentionLost':
      return `the tab was backgrounded on ${view}`
    case 'AttentionRegained':
      return `the tab came back on ${view}`
    case 'EntityOpened': {
      const source = str(payload, 'source')
      const opened = `opened entity ${str(payload, 'entity_id') ?? 'unknown'}`
      return source === null ? opened : `${opened} from ${source}`
    }
    case 'ProjectSwitched': {
      const from = str(payload, 'from_project_id')
      const to = `switched to project ${str(payload, 'to_project_id') ?? 'unknown'}`
      return from === null ? to : `${to} from ${from}`
    }
    case 'ExtractionQueued':
      return `queued ${str(payload, 'source_id') ?? 'a document'} for extraction`
    case 'ExtractionCancelled':
      return `cancelled extraction of ${str(payload, 'source_id') ?? 'a document'}`
    case 'DispatchRequested':
      return `${str(payload, 'action') ?? 'dispatched'} on topic ${
        str(payload, 'topic_id') ?? 'unknown'
      }`
    case 'SearchPerformed': {
      const found = num(payload, 'result_count')
      // The count is spelled out rather than reduced to "no results", because
      // `EmptyResultEncountered` is its own kind and this row saying "0
      // results" beside one of those is the pair a reader is looking for.
      return `searched “${str(payload, 'query_text') ?? ''}” — ${
        found === null ? 'result count unknown' : plural(found, 'result')
      }`
    }
    case 'AskSubmitted':
      return `asked “${str(payload, 'query_text') ?? ''}”`
    case 'ApprovalDecided': {
      const hidden = num(payload, 'hidden_ms')
      const decided = `${str(payload, 'decision') ?? 'decided'} after ${durationMs(
        num(payload, 'latency_ms'),
      )}`
      const withHidden =
        hidden !== null && hidden > 0 ? `${decided} (${durationMs(hidden)} hidden)` : decided
      // Both halves stated, unlike the hidden slice above. "details not
      // opened" is the click-through signal this event exists to carry, so
      // leaving it off the row would hide the interesting case rather than
      // the boring one. The wording is `expanded_details`' own caveat made
      // visible: it says what was opened, not what was read.
      const looked = payload['expanded_details']
      if (looked === true) return `${withHidden}, details opened`
      if (looked === false) return `${withHidden}, details not opened`
      return withHidden
    }
    case 'ActionUndone': {
      const target = str(payload, 'target_id')
      const undone = `undid ${str(payload, 'action_kind') ?? 'an action'}`
      return target === null ? undone : `${undone} on ${target}`
    }
    case 'ActionRetried': {
      const attempt = num(payload, 'attempt_number')
      const retried = `retried ${str(payload, 'action_kind') ?? 'an action'}`
      return attempt === null ? retried : `${retried}, attempt ${attempt}`
    }
    case 'EmptyResultEncountered': {
      const length = num(payload, 'query_length')
      const nothing = `nothing to show in ${str(payload, 'where') ?? view}`
      // The length rather than the text: this event is structural on purpose
      // -- `SearchPerformed` carries the words where words are warranted --
      // and a zero length is the difference between an empty query and a
      // query that found nothing.
      return length === null || length === 0
        ? nothing
        : `${nothing} for a ${length}-character query`
    }
    default: {
      // Exhaustiveness, not a fallback. Nothing reaches this arm: `kind` is
      // narrowed to `never` here, and a kind added to `INTERACTION_KINDS`
      // without an arm above makes this assignment a type error.
      const unreachable: never = event.kind
      return String(unreachable)
    }
  }
}

const isInteractionKind = (raw: string): raw is InteractionKind =>
  (INTERACTION_KINDS as readonly string[]).includes(raw)

const num = (payload: Readonly<Record<string, unknown>>, key: string): number | null => {
  const value = payload[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const str = (payload: Readonly<Record<string, unknown>>, key: string): string | null => {
  const value = payload[key]
  return typeof value === 'string' && value !== '' ? value : null
}
