/** Trimming a retrieved passage back to somewhere a reader can start.
 *
 * A mention is a chunk, not a quotation: `SlidingWindowChunker` cuts the
 * source every N characters with no regard for where a sentence or a markdown
 * block begins, so the first line of a chunk is usually the tail of something
 * that started in the previous one. "...anded down by the pontifices, which
 * Livy treats as" is not a passage anybody can read, and it is what the
 * mentions list showed for every entity.
 *
 * The rule is newline first, sentence second, whole chunk last, and the order
 * is the point. Chunk text is markdown, which is line-oriented -- a newline is
 * a block boundary (a heading, a list item, a new paragraph), so cutting there
 * lands on something that renders as a unit. Prose that runs long enough to
 * fill a chunk without a single line break is the case the newline rule cannot
 * serve, and sentence punctuation is the only boundary such a chunk has.
 *
 * Each rule falls through when it would leave nothing behind, which is what
 * keeps a chunk ending in a newline, or one that is a single unbroken
 * sentence, from rendering as an empty row. Showing a partial first sentence
 * is a poor result; showing a blank mention is a broken one.
 */

/** A sentence end followed by a space: `. `, `! `, `? `, and the same three
 *  behind a closing quote or bracket. Deliberately not a general
 *  abbreviation-aware splitter -- "T. Cornell" or "c. 509 BC" will cut early,
 *  and the cost of that is a snippet starting a few words late, against the
 *  cost of a parser this repo would then own. */
const SENTENCE_END = /[.!?]["')\]]?\s+/

/** `text` from the first boundary a reader can start at.
 *
 * Returns the input unchanged when no boundary leaves any text behind, which
 * includes the empty string.
 */
export const passageStart = (text: string): string => {
  const newline = text.indexOf('\n')
  if (newline !== -1) {
    const afterNewline = text.slice(newline + 1)
    if (afterNewline.trim().length > 0) return afterNewline.trimStart()
  }

  const sentence = SENTENCE_END.exec(text)
  if (sentence !== null) {
    const afterSentence = text.slice(sentence.index + sentence[0].length)
    if (afterSentence.trim().length > 0) return afterSentence
  }

  return text
}
