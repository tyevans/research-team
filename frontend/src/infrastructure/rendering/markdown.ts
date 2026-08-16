import DOMPurify from 'dompurify'
import { Marked } from 'marked'

/** Markdown, rendered by a library and sanitised by another.
 *
 * This replaces a hand-written block-and-inline renderer. That renderer was
 * careful — it built DOM nodes directly so model-authored text could never
 * become markup — but it was also a parser this project had to maintain, and it
 * covered only the subset of markdown the repo's own docs happened to use.
 * Anything else fell through as literal text.
 *
 * The safety property it was protecting is kept, and made stronger, by being
 * explicit rather than structural: `marked` produces HTML, `DOMPurify` removes
 * everything that could execute, and the allow-list below is the contract. A
 * sanitiser is a far better place to stake that claim than "we happen never to
 * call innerHTML", which is a property every future edit could quietly break.
 */

const marked = new Marked({
  gfm: true,
  breaks: false,
})

/** Two href shapes become real links: `http(s)`/`mailto`, and this app's own
 * `#/...` hash routes.
 *
 * Everything else — `javascript:`, `data:`, and any scheme invented later —
 * keeps its text and loses its href, so a reader sees the label and the target
 * without the page offering to follow it. This is enforced as a hook rather
 * than as a regex over the output, because the hook sees every anchor the
 * sanitiser kept, including ones produced by raw HTML in the source.
 */
const SAFE_SCHEME = /^(https?:|mailto:)/i

/** This app's own hash routes, the one other href shape this hook trusts. A
 * `[[src:...]]` reference expands to one of these before this file ever sees
 * it (see `references.ts`) -- but that is not why the pattern is safe, and
 * saying so here would be a claim the code doesn't enforce: this hook sees
 * every anchor DOMPurify kept, including one from raw `<a href="#/p/...">`
 * HTML a model wrote itself, and that reaches this same branch with no way
 * to tell it apart from an expanded reference. What actually makes it safe
 * is the *shape*, not the *provenance*: an `#/...` href is same-document by
 * construction, so it cannot execute, cannot leave the application, and
 * cannot reach another origin, regardless of who wrote it -- which is a
 * weaker capability than the `http(s)` links this hook has always allowed
 * through, model-authored or not.
 *
 * Matched against the route grammar `routes.ts` actually emits (`#/`,
 * `#/s/...`, `#/p/...`) rather than "anything starting with `#/`" -- `#//x`,
 * `#/\x` and the like all fail this pattern even though a hash fragment
 * couldn't navigate off-origin through them either. Defence in depth, not a
 * fix for a hole: don't loosen this back to `^#\/` thinking the narrower
 * form was arbitrary. */
const SAFE_HASH_ROUTE = /^#\/($|s\/|p\/)/

let hooked = false

const installHooks = (): void => {
  if (hooked) return
  hooked = true
  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (!(node instanceof Element) || node.tagName !== 'A') return
    const href = node.getAttribute('href')
    if (href && SAFE_SCHEME.test(href)) {
      node.setAttribute('target', '_blank')
      node.setAttribute('rel', 'noopener noreferrer')
      node.setAttribute('title', href)
      node.classList.add('md-link')
      return
    }
    // An in-app link, not an external one — no new tab, no rel (both
    // meaningless for a same-document route), and a class of its own rather
    // than reusing `md-link` outright, so styling can tell the two apart if
    // it ever needs to.
    if (href && SAFE_HASH_ROUTE.test(href)) {
      node.classList.add('md-link', 'md-link-internal')
      return
    }
    node.removeAttribute('href')
    node.setAttribute('title', href ?? '')
    node.classList.add('md-link-inert')
  })
}

const ALLOWED_TAGS = [
  'p',
  'br',
  'hr',
  'em',
  'strong',
  'del',
  'code',
  'pre',
  'blockquote',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'ul',
  'ol',
  'li',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
  'a',
  'span',
  'div',
  'input',
]

const ALLOWED_ATTR = ['href', 'title', 'class', 'align', 'type', 'checked', 'disabled']

/** Markdown as sanitised HTML, ready for a single `dangerouslySetInnerHTML`.
 *
 * That prop name is doing its job here: this is the one function in the
 * application permitted to produce markup from untrusted text, and everything
 * that makes it safe is in this file. */
export const renderMarkdown = (source: string): string => {
  installHooks()
  const html = marked.parse(source ?? '', { async: false })
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    // Task-list checkboxes are the only inputs GFM emits, and they arrive
    // already disabled. Keeping them makes a checklist in a document read as
    // one instead of as stray text.
    ADD_ATTR: ['disabled'],
  })
}

export const isEmptyMarkdown = (source: string): boolean => source.trim().length === 0
