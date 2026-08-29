import clsx from 'clsx'

import type { ProbeResult } from '@domain/settings/provider.ts'

/** What a connection test said, in words a person can act on.
 *
 * **Five outcomes get five sentences, and that is the whole point of this
 * component.** "It didn't work" over a wrong key and over a firewall send
 * somebody to completely different places — one is a paste, the other is a
 * network or a VPN — and collapsing them into one red line is how a person
 * spends twenty minutes re-copying a key that was always correct.
 *
 * The server's `detail` is rendered *beside* our sentence rather than instead
 * of it. Ours says what class of problem this is; theirs says what actually
 * happened. Neither is redundant: `detail` is often an HTTP status or an
 * exception string, which is precise and tells a non-operator nothing about
 * what to do next.
 */
export const TestOutcome = ({ result }: { result: ProbeResult }) => {
  const { heading, advice, tone } = COPY[result.outcome]

  return (
    <div
      // `role="status"` rather than `alert`: a test is something the person
      // just pressed and is watching, so it is announced politely rather than
      // interrupting. A failed *save* they did not expect is the `alert` case.
      role="status"
      className={clsx('flex flex-col gap-1 rounded-[3px] border p-2 text-sm', tone)}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <strong className="font-mono text-xs">{heading}</strong>
        {/* Latency only on success. On a failure it is the time spent finding
            out, which is not information anybody wants and reads as though the
            number meant something about the provider. */}
        {result.outcome === 'ok' && result.latencyMs !== null ? (
          <span className="font-mono text-xs text-fg-dim">{Math.round(result.latencyMs)} ms</span>
        ) : null}
        {result.models.length > 0 ? (
          <span className="font-mono text-xs text-fg-dim">
            {result.models.length} model{result.models.length === 1 ? '' : 's'}
          </span>
        ) : null}
      </div>
      <p className="m-0">{advice}</p>
      {result.detail ? (
        <p className="m-0 font-mono text-xs text-fg-faint">{result.detail}</p>
      ) : null}
      {/* The one failure that is *not* about this provider's configuration, and
          the one whose consequence is easy to miss: the picker below stays free
          text, and the reason is here rather than beside an empty menu. */}
      {result.ok && result.models.length === 0 ? (
        <p className="m-0 text-xs text-fg-dim">
          This provider does not list its models, so the model field stays free text.
        </p>
      ) : null}
    </div>
  )
}

/** One entry per outcome, exhaustively — a `Record` over the union rather than
 *  a lookup with a fallback, so a sixth outcome added to the contract is a
 *  compile error here rather than a blank box at run time. */
const COPY: Record<ProbeResult['outcome'], { heading: string; advice: string; tone: string }> = {
  ok: {
    heading: 'ok',
    advice: 'The credentials reached the provider.',
    tone: 'border-line bg-tint-ok text-fg',
  },
  unauthorized: {
    heading: 'unauthorized',
    advice:
      'The provider answered, and rejected the key. The address is right and the credential is not — re-paste it rather than changing the url.',
    tone: 'border-line bg-tint-fail text-fg',
  },
  unreachable: {
    heading: 'unreachable',
    advice:
      'Nothing answered at that address. The key was never tried, so it may well be fine — check the url, the network, and whether this host can see the provider at all.',
    tone: 'border-line bg-tint-fail text-fg',
  },
  unsupported: {
    heading: 'unsupported',
    advice:
      'This provider cannot be tested from here — usually an address with a {placeholder} still in it, or a provider whose sign-in this build cannot perform. Filling every placeholder field is the first thing to try.',
    tone: 'border-line bg-tint-held text-fg',
  },
  error: {
    heading: 'error',
    advice:
      'The test itself failed, which is not the same as the provider refusing. The detail below is what went wrong.',
    tone: 'border-line bg-tint-fail text-fg',
  },
}
