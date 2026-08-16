import type { ProjectId } from '@domain/shared/identifier.ts'

import { projectHref } from '../../presentation/routing/routes.ts'

/** `[[src:<id>]]`, `[[src:<id>@<seconds>]]`, `[[src:<id>@<start>-<end>]]` —
 *  everything a model can write to point at a source, and at a moment inside
 *  it. See the design's "The reference syntax".
 *
 * `<id>` is restricted to letters, digits, `.`, `_`, `#` and `-`. That is not
 * the full range `source_id` permits -- `corpus.py`'s `StoreDerivedText`
 * docstring says plainly that the domain leaves `source_id` unconstrained,
 * because naming is the caller's to choose. The restriction here is narrower
 * on purpose: it covers the shapes ids actually take in this codebase (slugs
 * like `wiki-trajan`, uploaded filenames, and the `#perceived` suffix
 * `perception.py`'s `DERIVED_SUFFIX` appends), while excluding a space, a
 * quote, or a slash -- characters that would either fail to round-trip through
 * this shorthand or have no business appearing in a citation id. An id outside
 * this set simply does not match, which is what "renders as literal text"
 * means for the case where a source genuinely has such an id: the shorthand
 * does not reach it, and the reader still has the visible `[[src:...]]` text
 * to report.
 */
const ID_CHARS = 'A-Za-z0-9_.#-'

/** Matches, in order of position, whichever of three things comes first:
 *  a fenced code block, an inline code span, or a well-formed reference.
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
 * The reference alternative doesn't also try to match malformed input. An
 * empty id, a space, an out-of-charset character, a non-digit offset -- none
 * of these complete the pattern, so the scan simply finds no match there and
 * that span of the source is left exactly as it was, which is the literal-
 * text fallback this whole function exists to guarantee. There is no second
 * "is this malformed" branch to keep in sync with the first.
 */
const TOKEN = new RegExp(
  '```[\\s\\S]*?```' + // fenced block, closed
    '|`[^`\\n]*`' + // inline code span
    `|\\[\\[src:([${ID_CHARS}]+)(?:@(\\d+)(?:-(\\d+))?)?\\]\\]`, // a reference
  'g',
)

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
 * negative offset, or a reference inside a fence or inline code -- comes back
 * unchanged, literal characters and all. That is deliberate, not a gap: a
 * reference that degrades to visible text is one a reader can report and a
 * developer can grep for; one that degraded to a blank or an error would be
 * the harder failure to notice. This function does not check that the id
 * names a real source -- see the design's resolution ruling -- so a
 * well-formed reference to an unknown id still links, to the document page's
 * own "not found" state.
 */
export const expandReferences = (source: string, projectId: ProjectId): string =>
  source.replace(TOKEN, (whole, id: string | undefined, start?: string, end?: string) => {
    // No `id` capture means this match was the fence or inline-code
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
    const query =
      start === undefined ? '' : end === undefined ? `?t=${start}` : `?t=${start},${end}`

    return `<a class="font-mono text-sm" href="${href}${query}">${id}</a>`
  })
