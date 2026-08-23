import { useEffect } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Toast } from '@application/notifications/toast-store.ts'
import { useToasts } from '@application/notifications/toast-store.ts'

import { Toasts } from './Toasts.tsx'

/** The notification stack, which is otherwise only visible for 3.8 seconds
 *  after something you did not plan.
 *
 * That is the argument for the page. A toast is the one surface in the console
 * a reader cannot go and look at: it appears in response to an event, it
 * expires on a timer, and the `bad` tone — the one that matters — is the one
 * you least want to reproduce on purpose. Every judgement about its wording,
 * its contrast and its stacking has had to be made from memory.
 *
 * **The stories hold the stack open using the store's own `hold()`**, which is
 * what the pointer and the keyboard do when a reader is reading a toast. That
 * is deliberate over faking timers: `Toasts.tsx` argues the hold at length,
 * and a gallery that suppressed expiry some other way would be showing a
 * component the application never renders. The consequence is real and worth
 * knowing while looking — these toasts never expire, so the fade-out is the
 * one behaviour this page cannot show.
 *
 * The three tones are not decoration. `bad` lives for 7000ms against the other
 * two's 3800, because the reader has to be able to finish reading a failure.
 * `EveryTone` is where the three can be compared for contrast at once, which
 * is the check no single toast in the wild allows.
 */
const meta: Meta = {
  title: 'shell/Toasts',
}

export default meta

type Story = StoryObj

const toast = (id: number, message: string, tone: Toast['tone']): Toast => ({
  id,
  message,
  tone,
  remainingMs: tone === 'bad' ? 7_000 : 3_800,
})

/** Seeds the store and holds it open for as long as the story is mounted.
 *
 *  `hold()`/`release()` rather than clearing the sweeper, because the hold is
 *  a real state the component has and the sweeper is an implementation
 *  detail. The counter is why this is safe to do per story: two mounted
 *  stories would hold twice and release twice, which is exactly what the
 *  pointer and the keyboard do when both are on the stack. */
const Seeded = ({ toasts }: { toasts: readonly Toast[] }) => {
  useEffect(() => {
    useToasts.setState({ toasts })
    useToasts.getState().hold()
    return () => {
      useToasts.getState().release()
      useToasts.setState({ toasts: [] })
    }
  }, [toasts])
  return <Toasts />
}

const Page = ({ children }: { children: React.ReactNode }) => (
  <div style={{ minHeight: 420, padding: 'var(--space-3)' }}>
    <p style={{ color: 'var(--fg-dim)', maxWidth: 520 }}>
      The page a toast arrives over. The stack is a fixed column at the end of the document, which
      is the reason F6 exists: a reader working here would otherwise reach it only by tabbing the
      whole page.
    </p>
    {children}
  </div>
)

/** All three tones at once — the comparison a live console never offers,
 *  because toasts arrive one at a time and outlive each other by seconds. */
export const EveryTone: Story = {
  render: () => (
    <Page>
      <Seeded
        toasts={[
          toast(1, 'Project archived.', 'neutral'),
          toast(2, 'Extraction finished — 412 entities.', 'good'),
          toast(3, 'Could not reach the grader. The answer was not recorded.', 'bad'),
        ]}
      />
    </Page>
  ),
}

/** One failure, alone, which is how it actually arrives.
 *
 *  Worth its own story because `EveryTone` flatters it: a red toast among
 *  three reads as one of a set, and a red toast alone on a page is the whole
 *  message. The wording has to work in the second case. */
export const AFailure: Story = {
  render: () => (
    <Page>
      <Seeded
        toasts={[toast(1, 'Could not reach the grader. The answer was not recorded.', 'bad')]}
      />
    </Page>
  ),
}

/** A message longer than the column.
 *
 *  Toasts are written by call sites all over the console and nothing bounds
 *  their length. What to check: the text wraps rather than truncating — a
 *  truncated failure is a failure a reader cannot act on — and the close
 *  button stays where it is rather than being pushed off. */
export const ALongMessage: Story = {
  render: () => (
    <Page>
      <Seeded
        toasts={[
          toast(
            1,
            'The extraction run stopped after 3 of 11 documents because the model returned no content twice in a row, and the remaining documents were left queued rather than marked failed.',
            'bad',
          ),
        ]}
      />
    </Page>
  ),
}

/** Several at once, which is what a burst of events produces.
 *
 *  The stack grows downward and the oldest is at the top. What to check: the
 *  column does not run off the viewport, and each toast is separately
 *  dismissible — a stack with one close button is a stack that makes a reader
 *  discard a message they have not read. */
export const AStack: Story = {
  render: () => (
    <Page>
      <Seeded
        toasts={[
          toast(1, 'Session forked at event 42.', 'neutral'),
          toast(2, 'Indexed 8 documents.', 'good'),
          toast(3, 'Consolidation merged 31 entities.', 'good'),
          toast(4, 'One source could not be fetched.', 'bad'),
          toast(5, 'Course authored — 6 areas.', 'good'),
        ]}
      />
    </Page>
  ),
}

/** Nothing pending.
 *
 *  `Toasts` renders on every page, so its empty state is what the console
 *  looks like almost all the time. Here so that "the stack draws nothing" is a
 *  state somebody has looked at, rather than an assumption — an empty region
 *  that nonetheless reserves space or takes a tab stop is a defect no other
 *  story would show. */
export const Empty: Story = {
  render: () => (
    <Page>
      <Seeded toasts={[]} />
    </Page>
  ),
}
