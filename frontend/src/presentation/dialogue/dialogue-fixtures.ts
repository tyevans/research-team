/** Turns and a project for the dialogue surface.
 *
 * Here rather than inline for `ask-fixtures.ts`'s reason, which is sharper on
 * this surface than on that one: a `DialogueTurn` has three flags -- `settled`,
 * `composing`, `concluded` -- and an inline literal per test is three places to
 * get one wrong. Each of them routes the turn down a path the test is not
 * about, and two of them render something (a thinking indicator, a conclusion
 * notice) that a reader of the failure would blame on the component.
 */
import type { DialogueTurn } from '@domain/dialogue/conversation.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

/** Fixed rather than generated, so a story's links are the same today as
 *  yesterday -- `ask-fixtures.ts` says why at greater length. */
export const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

/** One exchange, every field defaulted.
 *
 * `settled: true` is the default because an unsettled turn draws a thinking
 * indicator, and a test about who said what would otherwise be reading a page
 * mid-stream without having asked for one. */
export const exchange = (over: Partial<DialogueTurn> = {}): DialogueTurn => ({
  blocks: [{ kind: 'markdown', text: 'What makes you say it settled anything?' }],
  reply: 'It settled Arianism.',
  position: 0,
  activity: [],
  citations: [],
  concluded: false,
  error: null,
  settled: true,
  composing: false,
  ...over,
})
