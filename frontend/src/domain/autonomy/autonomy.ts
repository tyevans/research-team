/** How much rope the agent gets, per gated tool.
 *
 * Three facts about this model are load-bearing, and each of them exists to
 * stop a specific lie appearing on screen.
 *
 * **The policy is instance-wide.** There is one policy object serving every
 * session in the process, so nothing here is keyed by session. A per-session
 * shape would let two views hold different levels for the same tool and both
 * render confidently — see `AutonomyPanel` for how that is said out loud to
 * the reader, since a control that looks local while changing global behaviour
 * is worse than one you have to walk to.
 *
 * **The tool list comes from the server.** `gated` is the server's own
 * `GATED_TOOLS`, in the order to render them. Hardcoding it here would drift
 * the moment a tool is gated or ungated, and the drift would show as a missing
 * switch — a tool silently unmanageable from the web.
 *
 * **A level is a plain string.** Not a union, and not a zod enum at the edge:
 * a server that grows a fourth level must reach `levelMeaning`'s fallback and
 * render as itself, rather than failing validation and blanking the panel.
 */

/** The levels this build knows how to offer. A server may report others; see
 *  `levelMeaning`. */
export const AUTONOMY_LEVELS: readonly string[] = ['auto', 'ask', 'deny']

export interface AutonomyPolicyView {
  /** Keyed by tool name. Covers exactly `gated` when the server is this
   *  build's peer — `levelOf` returns null rather than guessing when it does
   *  not, because "ask" is a claim about safety nobody has made. */
  readonly levels: ReadonlyMap<string, string>
  /** Every tool under the policy, in the order to render switches. */
  readonly gated: readonly string[]
  /** The subset "allow all" deliberately leaves alone. Not a hazard rating:
   *  these *are* the review gates, the point where a person looks at what was
   *  produced before the run builds on it. */
  readonly stageGates: readonly string[]
}

/** What a write returned: what actually moved, and the whole policy after.
 *
 * `changed` is the honest thing to report back to the person who clicked. The
 * full `levels` map would let the UI claim eight changes where one was made.
 */
export interface AutonomyChange {
  readonly changed: ReadonlyMap<string, string>
  readonly policy: AutonomyPolicyView
}

export const emptyPolicy: AutonomyPolicyView = {
  levels: new Map(),
  gated: [],
  stageGates: [],
}

/** Null when the server named a tool in `gated` and gave it no level. Callers
 *  must render that as unknown rather than defaulting it. */
export const levelOf = (policy: AutonomyPolicyView, tool: string): string | null =>
  policy.levels.get(tool) ?? null

export const isStageGate = (policy: AutonomyPolicyView, tool: string): boolean =>
  policy.stageGates.includes(tool)

/** Whether every stage gate is still waiting on a person.
 *
 * The question "did allow-all appear to half-fail?" — a UI that ran allow-all
 * and showed `advance_stage` still asking, with no sentence explaining that
 * this was the point, reads as a bug rather than as a decision.
 */
export const stageGatesStillAsking = (policy: AutonomyPolicyView): readonly string[] =>
  policy.stageGates.filter((tool) => levelOf(policy, tool) !== 'auto')

/** A level in words. Unknown values come back as themselves, so a future
 *  server's fourth level reads as an unfamiliar setting rather than as an
 *  error, and never as one of these three. */
export const levelMeaning = (level: string): string => {
  if (level === 'auto') return 'runs without asking'
  if (level === 'ask') return 'waits for a person'
  if (level === 'deny') return 'refused outright'
  return `an unfamiliar level this build does not describe: ${level}`
}

/** The levels to offer for a tool, including one the server reported that this
 *  build does not know — otherwise selecting it would be impossible to undo,
 *  and the current setting would show as nothing selected. */
export const levelsToOffer = (current: string | null): readonly string[] =>
  current !== null && !AUTONOMY_LEVELS.includes(current)
    ? [...AUTONOMY_LEVELS, current]
    : AUTONOMY_LEVELS
