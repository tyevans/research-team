const LOWERCASE_WORDS: ReadonlySet<string> = new Set([
  'of',
  'the',
  'and',
  'a',
  'an',
  'in',
  'to',
  'for',
])

/** Sentence-case generated copy, cast to Title Case for display.
 *
 * The title reaching this function was written and stored **sentence case**
 * on purpose -- `grounding.ungrounded_runs` finds invented entity names by
 * capitalisation, and a Title Case string collapses into one capitalised run
 * that no single anchor contains, so a fully grounded Title Case title is
 * refused right along with an invented one (measured 2026-08-23). Sentence
 * case is the only shape that check can read, which is why casing happens
 * here, at display time, and nowhere upstream of it.
 *
 * The string this function receives has therefore already passed grounding,
 * so casing it cosmetically carries no trust risk -- it is not re-checked,
 * and never should be lowercased before that check runs (see this module's
 * own reasoning in the course-realization brief: down-casing first would
 * leave no capitalised runs for `ungrounded_runs` to find, which does not
 * weaken the check, it deletes it).
 *
 * The first word is always capitalised regardless of the stop-word list --
 * "the story of first contact" reads as "The story of first contact", not
 * "the Story of First Contact" with its own first word left alone.
 */
export function titleCase(s: string): string {
  return s
    .split(' ')
    .map((word, index) => {
      if (word === '') return word
      if (index > 0 && LOWERCASE_WORDS.has(word.toLowerCase())) return word.toLowerCase()
      return word[0]!.toUpperCase() + word.slice(1)
    })
    .join(' ')
}
