import type { ProjectId } from '@domain/shared/identifier.ts'

import { projectHref } from '../../presentation/routing/routes.ts'

/** `[[src:<id>]]`, `[[src:<id>@<seconds>]]`, `[[src:<id>@<start>-<end>]]` —
 *  everything a model can write to point at a source, and at a moment inside
 *  it. See the design's "The reference syntax".
 *
 * `<id>` is restricted to letters, digits, `.`, `_`, `#`, `-` and `:`. That is
 * not the full range `source_id` permits -- `corpus.py`'s `StoreDerivedText`
 * docstring says plainly that the domain leaves `source_id` unconstrained,
 * because naming is the caller's to choose. The restriction here is narrower
 * on purpose: it covers the shapes ids actually take in this codebase (slugs
 * like `wiki-trajan`, uploaded filenames, the `#perceived` suffix
 * `perception.py`'s `DERIVED_SUFFIX` appends, and `fetch_media.py`'s
 * `f"fetch:{digest}"`), while excluding a space, a quote, or a slash --
 * characters that would either fail to round-trip through this shorthand or
 * have no business appearing in a citation id. An id outside this set simply
 * does not match, which is what "renders as literal text" means for the case
 * where a source genuinely has such an id: the shorthand does not reach it,
 * and the reader still has the visible `[[src:...]]` text to report.
 *
 * `:` was added after review found `fetch_media.py:71` minting ids with one
 * and this file's original charset silently rejecting every reference to
 * them -- the exact "degrades to invisible text" failure this design exists
 * to avoid, reached from a direction neither sub-project's tests could see on
 * their own. Widening was chosen over renaming what `fetch_media` produces,
 * which would also orphan every id already stored.
 */
const ID_CHARS = 'A-Za-z0-9_.#:-'

/** Matches, in order of position, whichever of these comes first: a fenced
 *  code block, an inline code span, or a well-formed reference not sitting
 *  inside a markdown link's label.
 *
 * One regex rather than a reference-only pass over the whole string, because
 * a reference-only pass cannot tell a live reference from one sitting inside
 * a code fence showing the syntax -- both look identical to a regex that
 * doesn't also track where the fences are. Matching all three and only
 * replacing the reference alternative is how the fence and inline-code cases
 * come through untouched: they still match (so the scan doesn't recurse into
 * them looking for a reference to mangle) and the replacer hands them back
 * verbatim.
 *
 * **The fence has two alternatives, closed and unclosed, and the order
 * matters.** A first version here had only the closed form
 * (` ```[\s\S]*?``` `), and an unterminated fence broke it: with no closing
 * `` ``` `` anywhere in the string, that alternative fails outright, the scan
 * falls through to the inline-code alternative, which eats two of the three
 * opening backticks as an empty span, and resumes scanning *inside* the
 * unterminated block as ordinary text -- turning a `[[src:...]]` written
 * there into a live link. CommonMark's own answer for an unterminated fenced
 * block is that it runs to the end of the input, which is both the correct
 * parse and the fix: the second fence alternative below has no closing
 * requirement and is only reached once the first (which does) has exhausted
 * every possible close position.
 *
 * **The reference alternative is bounded by a same-line lookaround, not a
 * parser, for the markdown-link case.** `[see [[src:x]] here](url)` would
 * otherwise become a link nested inside `marked`'s own `<a>` for the
 * surrounding `[label](url)`, which is invalid markup. Real detection of
 * "am I inside a link's label" needs a parser -- brackets nest, links span
 * lines, and a regex has no stack. What's here instead is a same-line-only
 * heuristic: refuse to match a reference preceded on its line by an unmatched
 * `[`, or followed on its line by `](`. It catches the common single-level
 * case this codebase's own citations and prose actually produce and is
 * documented as a heuristic rather than a guarantee: a reference many
 * brackets deep, or split across a line break from its enclosing `[`/`]`,
 * is not something this lookaround sees, and `expandReferences.test.ts`
 * pins the bounded case it does catch rather than claiming more.
 *
 * **Four-backtick fences and indented (four-space) code blocks are not
 * tracked.** Disclosed here rather than handled: both are rare in
 * model-authored prose (which favours plain triple-backtick fences), and
 * widening the fence alternative to cover them is a parser-shaped problem for
 * a marginal input shape. A reference inside either would be transformed,
 * same as before this file existed -- a known gap, not a silent one.
 */
const TOKEN = new RegExp(
  '```[\\s\\S]*?```' + // fenced block, closed
    '|```[\\s\\S]*' + // fenced block, unclosed -- runs to end of input, per CommonMark
    '|`[^`\\n]*`' + // inline code span
    // a reference, not preceded by an unmatched same-line `[` and not
    // followed by a same-line `](` -- see the markdown-link paragraph above
    `|(?<!\\[[^[\\]\\n]*)\\[\\[src:([${ID_CHARS}]+)(?:@(\\d+)(?:-(\\d+))?)?\\]\\](?![^[\\]\\n]*\\]\\()`,
  'g',
)

/** Escapes the four characters that would otherwise let the matched id --
 *  interpolated below into the anchor's `title` and `aria-label` -- break out
 *  of its attribute, or out of the element if it were a text node again. `ID_CHARS` already excludes all four, so this currently never
 *  fires; it exists so that stays true if `ID_CHARS` is ever widened without
 *  the widener remembering this coupling. See the charset comment above.
 *
 *  Checked, not assumed, when `:` was added to `ID_CHARS`: `:` is not one of
 *  the four here, so it needs no HTML-text escaping, and in the other sink --
 *  the href -- it goes through `encodeURIComponent` inside `projectHref`
 *  (`encodeURIComponent(':')` is `'%3A'`), so it cannot alter the URL's
 *  structure there either. Both sinks stay safe with `:` admitted. */
const escapeText = (text: string): string =>
  text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!)

/** A pre-pass over markdown source, before `renderMarkdown` ever sees it.
 * Replaces every well-formed `[[src:...]]` reference with an `<a>` whose
 * `href` this function builds from validated parts -- the matched id and
 * digits, run through `encodeURIComponent` inside `projectHref`. Model text
 * is never interpolated into markup; it is only ever compared against a
 * regex and, on success, passed to the same URL builder the rest of the app
 * already uses (`projectHref(projectId, { facet: 'doc', id })`, as
 * `CitationList` and `GraphDetail` call it).
 *
 * Every invalid reference -- unmatched charset, empty id, non-integer or
 * negative offset, a reference inside a fence or inline code, or one sitting
 * in a markdown link's label -- comes back unchanged, literal characters and
 * all. That is deliberate, not a gap: a reference that degrades to visible
 * text is one a reader can report and a developer can grep for; one that
 * degraded to a blank or an error would be the harder failure to notice.
 * This function does not check that the id names a real source -- see the
 * design's resolution ruling -- so a well-formed reference to an unknown id
 * still links, to the document page's own "not found" state.
 *
 * **The anchor's visible text is a superscript number, not the id.** A source
 * id here is a fifty-character slug, and printing it inline put three of them
 * in a five-line paragraph, in monospace, wrapping mid-sentence; the slug
 * carries nothing a reader can act on. The degradation promise above is about
 * the *invalid* case and is untouched. For the valid case the id is preserved
 * on the anchor's `title` and `aria-label`, so it is still visible on hover,
 * still in the DOM, and still greppable in the rendered page -- the reporting
 * path the promise exists to keep is the same path, one hover longer.
 *
 * **Numbering is per call, which is per markdown block, which is per lesson.**
 * The counter is a local, so a page rendering a unit and three lessons shows
 * four independent sequences each starting at 1. That is the right unit -- a
 * lesson is what a reader reads at once -- but it does mean two "1"s on one
 * page name different sources, which is why the id has to stay reachable on
 * the element rather than only in a footnote list this function cannot see.
 * A repeated id reuses its number: the key is the id alone, not the id and
 * offset, because two moments in one recording are one source.
 */
export const expandReferences = (source: string, projectId: ProjectId): string => {
  const numbers = new Map<string, number>()

  return source.replace(TOKEN, (whole, id: string | undefined, start?: string, _end?: string) => {
    // No `id` capture means this match was a fence or inline-code
    // alternative, not a reference -- hand it back untouched, syntax and all.
    if (id === undefined) return whole

    const href = projectHref(projectId, { facet: 'doc', id })
    // Not a W3C media fragment (`#t=252`) -- a URL has exactly one fragment,
    // the text after its first `#`, and this app's href is already a hash
    // route (`#/p/<id>/doc/<id>`). A second `#t=252` appended after it isn't
    // a fragment at all, just characters inside the one fragment that already
    // started; no browser applies it to anything. So the seek can't be free
    // the way a plain `<video src="…#t=252">` gets it -- it has to be
    // ordinary JavaScript in the player, which is where it was always going
    // to happen under a hash router regardless. The offset travels as an
    // ordinary query string on the hash route instead, which the router
    // already knows how to parse without any special-casing.
    // A range reference (`@start-end`) seeks to its start and nothing more:
    // `?t=` is parsed by `parseSeekSeconds` in routes.ts, which reads one
    // number and rejects anything else (`Number('252,310')` is `NaN`) --
    // there is no second field for an end to occupy, and emitting `end` here
    // used to produce a `?t=252,310` that function then refused, so a range
    // reference seeked nowhere. The end is simply dropped rather than encoded
    // some other way: the start is where the quote the reference points at
    // begins, which is what seeking means for a reference, and a player has
    // no use for "and stop at 310" today. `references.test.ts` pins that a
    // range collapses to its start's `?t=`.
    const query = start === undefined ? '' : `?t=${start}`

    const existing = numbers.get(id)
    const number = existing ?? numbers.size + 1
    if (existing === undefined) numbers.set(id, number)

    // `md-ref` is a named class in `markdown.css`, not a Tailwind utility.
    // The anchor also picks up `md-link`/`md-link-internal` from
    // `markdown.ts`'s sanitiser hook, and those live in the same unlayered
    // stylesheet -- a utility would sit in the class attribute and lose the
    // cascade to them without anything failing. See CLAUDE.md on unlayered
    // rules beating layered utilities.
    //
    // `aria-label` rather than visually-hidden text: the number is the whole
    // visible content, and a bare numeral read aloud mid-sentence is noise.
    // Both attributes go through `escapeText` for the same reason the text
    // node did -- `ID_CHARS` forbids `"` today, and this stays correct if it
    // stops doing so.
    const label = escapeText(id)
    return (
      `<sup class="md-ref"><a href="${href}${query}"` +
      ` title="${label}" aria-label="Source ${number}: ${label}">${number}</a></sup>`
    )
  })
}
