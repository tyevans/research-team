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
