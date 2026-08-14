/** The one wording for "this stage declares checks nothing implements".
 *
 * It lived inline in `course/Findings.tsx` until `session/GateReview.tsx`
 * needed to say the same thing about the same data arriving by a different
 * route. Two copies of a sentence this specific drift silently — one gets a
 * pluralisation fix and the other does not — and the sentence is the whole
 * point: a declared check that never ran is a guarantee the preset claims and
 * nothing provides, so the reader has to be told that *nothing* is known about
 * what it would have found, not merely that it found nothing.
 *
 * A string rather than a component because the two callers wrap it in
 * different markup — a list item beside a chip in one, a warning block in the
 * other — and only the words are shared.
 */
export const unimplementedChecksWarning = (checks: readonly string[]): string =>
  `This stage declares ${checks.length} check${checks.length === 1 ? '' : 's'} that nothing implements: ${checks.join(', ')}. Nothing they would have found is known.`

/** The severity tones of a findings chip, as utility dressing.
 *
 * **This module rather than `GateReview.tsx`, and the move is a bug fix.** The
 * map was written there when `.chip-invariant` and its four siblings left
 * `course.css` (PR #169), on the argument that `GateReview` was the only caller
 * — and it was not. `course/Findings.tsx` renders `<Chip tone={severity}>` for
 * exactly these five strings, and has since that commit been asking for classes
 * no stylesheet declares: five severities collapsed into one grey, on the
 * project page's Findings tab, with no error and no failing test. That is the
 * orphan the tones were moved to *avoid*, reintroduced by the move. Found by
 * enumerating what `MATERIAL`'s facets write, in increment C slice 3.
 *
 * A shared module is the answer rather than one component importing the other's
 * constant: the two callers are in different feature directories and neither
 * owns severity — the reviewer prompts do, which is why the lookup is a
 * `Record<string, …>` with a miss that means "the default", not an exhaustive
 * union.
 *
 * `dress` **replaces** `Chip`'s default trio rather than overriding it. Both
 * would be `@layer utilities`, where the winner between two colour utilities is
 * Tailwind's sort order and not the class attribute's. Replacement has one
 * answer.
 *
 * The values are `course.css`'s own. Where a hex had a token it is named —
 * `#241417` is `--color-tint-fail`, `#45272a` is `--color-tint-fail-line`,
 * `#241d10` is `--color-tint-held`, `#1a1630`/`#3a3060` are the session tints.
 * `critic_gate`'s two have no token and stay arbitrary rather than being
 * rounded to a neighbour. `advisory` set only a colour, so it keeps the base
 * hairline and no fill, which is what it looked like.
 */
export const SEVERITY_DRESS: Record<string, string> = {
  invariant: 'text-k-failure border-tint-fail-line bg-tint-fail',
  blocking: 'text-accent border-accent-dim bg-tint-held',
  advisory: 'text-fg-dim border-line',
  human_gate: 'text-k-session border-tint-session-line bg-tint-session',
  critic_gate: 'text-k-compaction border-[#2b3a42] bg-[#121b20]',
}
