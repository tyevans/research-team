/** The sentences both autonomy surfaces say, written once.
 *
 * Not a stylistic preference. Two controls over the same instance-wide policy
 * that describe its scope differently teach the reader that one of them is
 * lying, and they cannot tell which. Wording drift here is a correctness bug,
 * so the wording lives in one module and both surfaces import it.
 */

/** The warning that keeps this from being a trap.
 *
 * A toggle sitting inside one session's drawer, or on one project's page,
 * looks local. It is not: there is a single policy object serving every
 * session in the process, and flipping a switch here changes what the agent
 * may do everywhere. A control that looks local while changing global
 * behaviour is worse than one you have to walk to — so this is stated on the
 * control itself, not in a tooltip, and not once at the top of a page the
 * reader may have scrolled past.
 */
export const INSTANCE_WIDE =
  'This applies to every session on this instance, not just this one. ' +
  'The change is recorded on the session you make it from.'

/** Why allow-all leaves the stage gate alone.
 *
 * Said out loud, because the alternative is worse in both directions: silence
 * makes a deliberate exclusion look like a half-failed request, and hiding the
 * exclusion would let somebody auto every stage boundary without noticing they
 * had. The floor on a stage gate is not a hazard rating — it *is* the review
 * point where a person looks at what was produced before the run builds on it.
 */
export const STAGE_GATE_HELD =
  'left asking on purpose: it is the workflow review gate, the point where a ' +
  'person looks at what was produced before the run builds on it. Auto-ing it ' +
  'lets a run cross every stage boundary with nobody looking.'

export const NO_SESSION =
  'No session is attached here, so there is nothing to record a change against. ' +
  'These levels are read-only until one is.'

/** The 404 from an unwired policy. Distinct from a failure, and emphatically
 *  distinct from "nothing is gated" — which is what an empty panel would
 *  imply. */
export const NO_POLICY =
  'This build does not expose an autonomy policy, so it cannot say what the ' +
  'agent may do without asking.'
