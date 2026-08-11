import { useId, useState } from 'react'

import type { Approval, ApprovalAnswer, ApprovalDecision } from '@domain/approval/approval.ts'
import { safeJson } from '@domain/conversation/message.ts'
import type { ApprovalId } from '@domain/shared/identifier.ts'

import { Button, type ButtonTone } from '../common/primitives.tsx'
import { GateReview } from './GateReview.tsx'

/** Gated calls, waiting on a person.
 *
 * A card can be answered here, in the REPL, or in another tab — whichever gets
 * there first. `ApprovalSettled`, not this click handler, is what takes it
 * down; that is what makes the other two paths work too, instead of only the
 * one this tab drove.
 *
 * **Every decision is named on every card, including the ones this gate will
 * not take.** A tool gate excludes `respond` (`approval.py`'s
 * `ALLOWED_DECISIONS`, and its docstring is where the wording below comes
 * from), a stage gate allows it. Hiding the excluded one would make the
 * console's vocabulary depend on server state that nothing on screen reports
 * — the reader sees three controls here and four there and has no way to tell
 * whether the fourth is missing, broken, or was never a thing. That is R-F6.9
 * (empty is not the same as unavailable) wearing a different hat. So an
 * unavailable decision renders `disabled`, by name, with its reason beside it.
 *
 * `disabled` rather than `aria-disabled`: there is nothing to do with the
 * control, so it should not take focus and should not look like it might
 * respond. The reason is a real element referenced by `aria-describedby`, so a
 * screen-reader user gets the explanation the sighted reader gets rather than
 * a button that is silently unusable.
 *
 * Styled with Tailwind utilities. The `.approval*` rules in
 * `conversation.css` are deleted rather than left behind — see `GateReview`
 * for what that trade costs.
 */
export const Approvals = ({
  approvals,
  deciding,
  onDecide,
}: {
  approvals: ReadonlyMap<ApprovalId, Approval>
  deciding: ApprovalId | null
  onDecide: (approval: Approval, answer: ApprovalAnswer) => void
}) => (
  <div className="flex flex-col gap-2">
    {[...approvals.values()].map((approval) => (
      <ApprovalCard
        key={approval.id}
        approval={approval}
        busy={deciding === approval.id}
        onDecide={onDecide}
      />
    ))}
  </div>
)

/** The four decisions, in the order a reader should meet them.
 *
 * A fixed list rather than a map over `allowedDecisions`, which is the whole
 * point: iterating what the server allows is exactly how a decision goes
 * missing without anybody noticing.
 */
const DECISIONS: readonly { decision: ApprovalDecision; label: string; tone: ButtonTone }[] = [
  { decision: 'approve', label: 'Approve', tone: 'accent' },
  { decision: 'edit', label: 'Edit the call', tone: 'default' },
  { decision: 'reject', label: 'Reject', tone: 'quiet' },
  { decision: 'respond', label: 'Respond instead', tone: 'quiet' },
]

/** Why a decision this gate does not take is not on offer.
 *
 * `respond` is quoted from `ALLOWED_DECISIONS` in
 * `research_team/infrastructure/agent/approval.py`, because that comment is
 * the actual reason and paraphrasing it would leave two sources for one rule.
 * The other three have no real-world exclusion today and their wording is
 * therefore a guess at a shape rather than a quotation — if one of them starts
 * being excluded, the server's reason belongs here in place of the guess.
 */
const UNAVAILABLE: Record<ApprovalDecision, string> = {
  approve: 'This gate does not accept a plain approval.',
  edit: 'This gate does not accept edited arguments.',
  reject: 'This gate cannot be refused from here.',
  respond:
    'Answering on the tool’s behalf invents a result, and this log is supposed to record what actually happened.',
}

/** One gated call, and the decision being composed about it.
 *
 * `edit` and `respond` are modes rather than buttons that post immediately,
 * because neither means anything without a payload: an `edit` with no
 * `editedArgs` re-runs the call the reviewer was objecting to, and a `respond`
 * with no `message` invents an empty tool result. A bare button for either
 * would be a control that looks like it did something and did the wrong thing.
 */
const ApprovalCard = ({
  approval,
  busy,
  onDecide,
}: {
  approval: Approval
  busy: boolean
  onDecide: (approval: Approval, answer: ApprovalAnswer) => void
}) => {
  const [mode, setMode] = useState<'edit' | 'respond' | null>(null)
  const reasonIds = useId()

  const allows = (decision: ApprovalDecision) => approval.allowedDecisions.includes(decision)

  return (
    <article className="flex flex-col gap-2 rounded-md border border-k-tool bg-bg-raise p-2">
      <div className="flex flex-wrap items-baseline gap-2 font-mono text-sm">
        <span>wants to run</span>
        <b className="font-semibold text-k-tool">{approval.toolName}</b>
      </div>
      {approval.description ? (
        <div className="text-xs text-fg-dim">{approval.description}</div>
      ) : null}
      <pre className="m-0 max-h-[120px] overflow-auto font-mono text-xs whitespace-pre-wrap text-fg-faint">
        {safeJson(approval.args)}
      </pre>

      {approval.context ? (
        <GateReview context={approval.context} sessionId={approval.sessionId} />
      ) : null}

      <div className="flex flex-col gap-2">
        {DECISIONS.map(({ decision, label, tone }) => {
          const available = allows(decision)
          const reasonId = `${reasonIds}-${decision}`
          return (
            <div key={decision} className="flex flex-wrap items-center gap-2">
              <Button
                small
                tone={tone}
                disabled={!available || busy}
                aria-describedby={available ? undefined : reasonId}
                aria-pressed={
                  decision === 'edit' || decision === 'respond' ? mode === decision : undefined
                }
                onClick={() => {
                  if (decision === 'edit' || decision === 'respond') {
                    setMode((current) => (current === decision ? null : decision))
                    return
                  }
                  onDecide(approval, { decision })
                }}
              >
                {label}
              </Button>
              {available ? null : (
                <span id={reasonId} className="text-xs text-fg-dim">
                  {UNAVAILABLE[decision]}
                </span>
              )}
            </div>
          )
        })}
      </div>

      {mode === 'edit' ? (
        <EditForm
          approval={approval}
          busy={busy}
          onSubmit={(editedArgs) => onDecide(approval, { decision: 'edit', editedArgs })}
        />
      ) : null}
      {mode === 'respond' ? (
        <RespondForm
          busy={busy}
          onSubmit={(message) => onDecide(approval, { decision: 'respond', message })}
        />
      ) : null}
    </article>
  )
}

/** The call, as arguments a person can change before it runs.
 *
 * JSON in a textarea rather than a generated form: the arguments are whatever
 * the tool's schema says, this component has no schema, and a form built by
 * guessing at the shape would silently drop the keys it failed to guess. The
 * cost is that the reviewer has to type valid JSON, which is why an unparsable
 * edit is refused here with the parser's own message rather than posted and
 * rejected server-side.
 */
const EditForm = ({
  approval,
  busy,
  onSubmit,
}: {
  approval: Approval
  busy: boolean
  onSubmit: (editedArgs: unknown) => void
}) => {
  const [text, setText] = useState(() => safeJson(approval.args))
  const [error, setError] = useState<string | null>(null)
  const fieldId = useId()

  return (
    <div className="flex flex-col gap-2 rounded-md border border-line bg-bg-panel-2 p-2">
      <label htmlFor={fieldId} className="text-xs text-fg-dim">
        Arguments to run instead
      </label>
      <textarea
        id={fieldId}
        className="min-h-[7em] w-full resize-y rounded-md border border-line bg-bg p-2 font-mono text-xs text-fg"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      {error ? (
        <p role="alert" className="m-0 text-xs text-k-failure">
          {error}
        </p>
      ) : null}
      <div>
        <Button
          small
          tone="accent"
          disabled={busy}
          onClick={() => {
            try {
              const parsed: unknown = JSON.parse(text)
              setError(null)
              onSubmit(parsed)
            } catch (parseError) {
              setError(
                `That is not valid JSON, so nothing was sent: ${
                  parseError instanceof Error ? parseError.message : String(parseError)
                }`,
              )
            }
          }}
        >
          Run the edited call
        </Button>
      </div>
    </div>
  )
}

/** A result written by a person, standing in for the call.
 *
 * Empty is refused rather than sent: an empty `message` is a tool result of
 * "", which the agent reads as the tool having answered nothing — which is a
 * different and worse outcome than the gate staying open.
 */
const RespondForm = ({
  busy,
  onSubmit,
}: {
  busy: boolean
  onSubmit: (message: string) => void
}) => {
  const [message, setMessage] = useState('')
  const fieldId = useId()

  return (
    <div className="flex flex-col gap-2 rounded-md border border-line bg-bg-panel-2 p-2">
      <label htmlFor={fieldId} className="text-xs text-fg-dim">
        What to tell the agent instead of running it
      </label>
      <textarea
        id={fieldId}
        className="min-h-[5em] w-full resize-y rounded-md border border-line bg-bg p-2 text-md text-fg"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
      />
      <div>
        <Button
          small
          tone="accent"
          disabled={busy || message.trim().length === 0}
          onClick={() => onSubmit(message)}
        >
          Send this instead
        </Button>
      </div>
    </div>
  )
}
