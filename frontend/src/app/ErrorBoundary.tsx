/** The last thing between a render-time throw and a white screen.
 *
 * Until this file there was no boundary anywhere in `frontend/src`: a throw
 * during render unmounted the whole tree and left `#root` empty, with the
 * error visible only in the browser console and no control on the page to get
 * back. Per-pane `isError` handling is good and covers the *fetch* path; this
 * covers the render path, which nothing did.
 *
 * It is being built now rather than when it first bites because the two
 * workstreams landing next both introduce state that can be absent or
 * malformed at render time -- a session that expired between load and paint,
 * a settings payload of a shape nobody anticipated. Those fail during render,
 * not in a query.
 *
 * **A class component, and it has to be.** `componentDidCatch` and
 * `getDerivedStateFromError` have no hook equivalent; React has never shipped
 * one. `react-error-boundary` was considered and declined for a component this
 * small (~1.6 kB gzipped against a bundle already over budget, for a
 * `resetKeys` prop and a render-prop API neither of which this needs).
 *
 * What the fallback deliberately is not: an apology. Three ways out, in
 * increasing cost -- try again in place, go home, reload the page -- and the
 * error itself on screen rather than swallowed, because the person who hits
 * this is usually the person who can fix it and "something went wrong" makes
 * them open devtools to learn what this component already knew.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'

import { errorMessage } from '@application/ports/errors.ts'

import { useInteractionLog } from './interaction-log-provider.tsx'

/** What a caught error is reported as. Not a `console.error` call: React
 *  already logs one, and a second is noise. */
export interface ErrorReport {
  /** Which boundary caught it -- `'root'` or `'console'` today. Structural, so
   *  a consumer can tell "the whole application failed to mount" from "one
   *  route's content did". */
  readonly where: string
  readonly error: Error
  readonly componentStack: string | null
}

interface Props {
  readonly where: string
  readonly children: ReactNode
  /** Called once per caught error, from `componentDidCatch`. Never called
   *  during render, which matters: `record` on the interaction log emitter
   *  mutates a queue, and doing that from `getDerivedStateFromError` would be
   *  a side effect in a static React lifecycle method. */
  readonly onError?: (report: ErrorReport) => void
  /** Retrying is a decision the boundary cannot make for the caller: clearing
   *  the error re-renders exactly the subtree that just threw, so a caller
   *  with nothing else to change gets the same throw back. Reported so a
   *  consumer can distinguish a transient failure from a loop. */
  readonly onRetry?: (attempt: number) => void
}

interface State {
  readonly error: Error | null
  readonly componentStack: string | null
  /** How many times "Try again" has been pressed since this boundary was
   *  last cleared. Shown once it is above one: a person pressing it a third
   *  time is being told, rather than left to conclude the button is dead. */
  readonly attempts: number
}

const EMPTY: State = { error: null, componentStack: null, attempts: 0 }

export class ErrorBoundary extends Component<Props, State> {
  override state: State = EMPTY

  static getDerivedStateFromError(error: unknown): Partial<State> {
    // Normalised here rather than at every read: React passes whatever was
    // thrown, and `throw 'oops'` is legal JavaScript that a `.message` read
    // would turn into a second, more confusing crash inside the fallback.
    // `attempts` is deliberately *not* reset here. A retry re-renders the
    // subtree, which for a permanent fault throws again and lands back in
    // this method -- so resetting would hold the counter at zero for exactly
    // the case it exists to name, and the notice below would never appear.
    // The cost: a genuinely different error arriving later inherits the
    // count. `goHome` clears it, and so does a reload; nothing else has to.
    return { error: error instanceof Error ? error : new Error(errorMessage(error)) }
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    const componentStack = info.componentStack ?? null
    this.setState({ componentStack })
    this.props.onError?.({
      where: this.props.where,
      error: error instanceof Error ? error : new Error(errorMessage(error)),
      componentStack,
    })
  }

  private readonly retry = (): void => {
    const attempt = this.state.attempts + 1
    this.props.onRetry?.(attempt)
    this.setState({ error: null, componentStack: null, attempts: attempt })
  }

  private readonly goHome = (): void => {
    // The hash first, then the reset: clearing the error re-renders the
    // subtree, and re-rendering it against the route that threw is how "Go
    // home" would land straight back on this fallback.
    window.location.hash = '#/'
    this.setState(EMPTY)
  }

  override render(): ReactNode {
    const { error, componentStack, attempts } = this.state
    if (error === null) return this.props.children

    return (
      <div className="error-boundary" role="alert">
        <h2 className="error-boundary-heading">The console stopped drawing this page.</h2>
        <p className="error-boundary-detail">
          Nothing you were reading has been lost — this is the page, not the data. Try again first;
          if it comes straight back, go home.
        </p>
        {/* The error itself, on the page. The whole reason this component is
            not a blank apology: a name and a message identify most render
            throws to the person looking at them, and the alternative is
            asking them to open devtools for something already in hand. */}
        <p className="error-boundary-message">
          <strong>{error.name}</strong>: {error.message || '(no message)'}
        </p>
        {attempts > 1 ? (
          <p className="error-boundary-detail">
            Tried {attempts} times. This one is not going away on its own.
          </p>
        ) : null}
        <div className="error-boundary-actions">
          <button type="button" className="btn btn-accent" onClick={this.retry}>
            Try again
          </button>
          <button type="button" className="btn" onClick={this.goHome}>
            Go home
          </button>
          {/* Last, and the only one that cannot fail: a reload rebuilds every
              provider above this boundary, which is the case "Try again"
              cannot reach -- the throw came from state this subtree does not
              own. */}
          <button type="button" className="btn btn-quiet" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
        {componentStack === null ? null : (
          <details className="error-boundary-stack">
            <summary>Component stack</summary>
            <pre>{componentStack.trim()}</pre>
          </details>
        )}
      </div>
    )
  }
}

/** The same boundary, reporting to the interaction log.
 *
 * A separate component rather than a prop on every call site because
 * `useInteractionLog` is a hook and `ErrorBoundary` is a class. It must be
 * rendered *below* `InteractionLogProvider` -- rendered above it, the hook
 * reads the silent default context and records into nothing, which is
 * indistinguishable from working (CLAUDE.md, "The interaction log"). The
 * outermost boundary in `App.tsx` is plain `ErrorBoundary` for exactly that
 * reason: it sits above the provider, so it has no log to report to, and
 * saying so is better than a `useInteractionLog()` that silently drops.
 */
export const LoggedErrorBoundary = ({
  where,
  children,
}: {
  where: string
  children: ReactNode
}) => {
  const log = useInteractionLog()

  return (
    <ErrorBoundary
      where={where}
      onError={(report) =>
        log.record('RenderErrorRaised', {
          where: report.where,
          error_name: report.error.name,
          // A length, not the text. The message is the field most likely to
          // carry a project name, a file path or a fragment of what somebody
          // typed, and the vocabulary's rule is that free text is recorded as
          // shape unless it is on the allowlist.
          message_length: report.error.message.length,
        })
      }
      onRetry={(attempt) =>
        log.record('ActionRetried', { action_kind: 'render', attempt_number: attempt })
      }
    >
      {children}
    </ErrorBoundary>
  )
}
