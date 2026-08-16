# Rendering media where prose is rendered

The corpus can acquire a video, transcribe it, and tell you that a claim came
from character 4,210 of its transcript. It cannot show you the moment.

This is sub-project 4 of four, and the last. Sub-project 1 gave media a place to
live, 2 made it legible, 3 made it arrive. This one makes it *appear* — in the
three places that currently know how to draw text and nothing else.

## The three surfaces, and why they are one design

- **A finding citing a moment.** Citations already carry `{sourceId, start, end}`
  and render as a link to the document (`GraphDetail.tsx:256-264`). For a media
  source that link opens a player at zero, which is the wrong second of an hour.
- **Markdown the model emits.** The model writes prose about a source it has
  read and cannot point at it. `Markdown` (`presentation/common/content.tsx:18`)
  renders it, and today the best the model can do is name a source in words.
- **The Ask page's answers**, which is the surface where most people meet what
  the corpus knows, and which renders through the same `Markdown` component.

The common problem is not display. It is that **a model writing prose has to
name a source and a moment in it without being able to emit a URL that points
anywhere.** Solve that once and all three surfaces follow, because two of them
already share a renderer and the third already has the coordinates.

## What already exists, and what that forecloses

Everything in this section is why the design below is small.

**`locators.resolve(locator_map, start, end)`** turns a character span into the
moments it covers, returning `TimeSpan`/`CharSpan`/`ByteRange` locators. It is
pure, total, never raises, and is **called by nothing outside tests** — its own
docstring names "a citation renderer" as an intended caller. The arithmetic of
"which second is this quote from" is done.

**Range support on the content route** was added in sub-project 1, argued for on
its own terms, and that spec notes it "is also what makes a seeked player
possible at all, so sub-project 4 inherits it rather than adding it."

**`DocumentReader`** already plays video and audio and renders images.

**`renderMarkdown` is the single sanitisation point.** `dangerouslySetInnerHTML`
appears exactly once in this application, in `Markdown`, and what it is handed
has been through DOMPurify with a closed tag allow-list. The component's own
docstring says the point of that arrangement is to make the claim *checkable by
grep rather than by reading every renderer*. **Any design that adds a second
place where model-authored text becomes markup destroys that property**, and the
property is worth more than this feature.

## The reference syntax

**The model emits an identifier and an offset. It never emits a URL.**

```
[[src:wiki-trajan-column]]              a source
[[src:keynote-2026@252]]                a source at 4:12
[[src:keynote-2026@252-310]]            a source across a range
```

Chosen over the three alternatives, and the reasoning matters more than the
brackets:

- **A markdown link with a custom scheme** (`[label](source:abc#t=252)`) reads
  more naturally and was rejected on the sanitiser. DOMPurify strips unknown
  schemes, so the reference would survive as an inert `<a>` with no href — a
  reference that silently renders as unlinked text is the failure mode hardest
  to notice, because it looks like prose that just did not get marked up.
- **A URL the model writes directly** is the thing this design exists to
  prevent.
- **A fenced block** (```` ```source ````) is unusable inline, and a citation is
  inline by nature.

`[[…]]` survives both `marked` and DOMPurify untouched, because it is ordinary
text. That is the property being bought: **an unresolved reference degrades to
visible literal text**, which a reader can report and a developer can grep,
rather than to silence.

**Rulings taken:**
- **The offset is seconds, an integer.** Not `4:12`, because a model writing
  `1:04:12` and a model writing `64:12` should not produce different results,
  and parsing human durations is a guessing game the renderer should not play.
  The seconds come from `locators.resolve`, which already speaks `start_s`.
- **A range is `start-end`**, and a bare `@252` is a point. A point is what a
  citation usually wants; a range is what a quote spanning several segments
  produces.
- **The id charset is restricted**, and narrower than `source_id` itself
  permits — `corpus.py`'s `StoreDerivedText` docstring leaves `source_id`
  unconstrained, but the implementation admits only letters, digits, `.`,
  `_`, `#`, `-` and `:` (`references.ts`'s `ID_CHARS`). That covers every
  shape an id actually takes in this codebase (slugs, uploaded filenames, the
  `#perceived` suffix, `fetch_media.py`'s `fetch:<digest>`) while excluding a
  space, a quote, or a slash. A reference whose id fails that check is **not
  resolved and not linked** — it renders as its literal text. Validation is
  not a nicety here: the id becomes part of a URL we construct.

## Resolution, and where the URL comes from

A pre-pass over the markdown source, **before** `renderMarkdown`, replaces each
valid reference with an `<a>` whose href **this code constructs** from validated
parts — never from model text. Then the existing sanitiser runs, unchanged, over
the result.

That ordering is the whole security argument and is worth stating plainly:
- The model supplies an id and an integer. Nothing else.
- The href is built by us from a known route shape, exactly as
  `projectHref(projectId, {facet: 'doc', id: sourceId})` already builds it.
- DOMPurify still runs last, so the pre-pass cannot introduce markup the
  allow-list would have rejected.
- `dangerouslySetInnerHTML` remains in exactly one place, so the grep-checkable
  property survives.

**The pre-pass must be total.** A malformed reference, an unknown id, a
non-integer offset: all render as literal text. It runs on every assistant
message on every stream frame, and `Markdown` is memoised on the source
specifically because re-parsing per frame is "the difference between a smooth
log and a stuttering one" — so the pre-pass is memoised with it, not separately.

**Ruling: the pre-pass does not check that the source exists.** Checking would
mean a corpus read inside a renderer, on every frame, for every reference. An id
that is well-formed but unknown produces a link that leads to the document
page's own "not found" state, which is a worse experience than a live check and
a much better one than a stuttering conversation. The document page already has
that state and it is honest.

## Seeking

A reference carrying an offset does **not** append a media fragment
(`#t=252`) to the content route — a hash-routed URL already has its one
fragment spent on the route itself (`#/p/<id>/doc/<id>`), so a second `#t=`
would just be inert characters inside the fragment that already started. The
offset instead travels as an ordinary `?t=` query string on that hash route
(`references.ts`), which `parseSeekSeconds` (`routes.ts`) reads and
`DocumentReader` seeks on. A range offset (`@start-end`) collapses to its
start — there is no second field in `?t=` for an end to occupy, and a reader
seeking to where a quote begins is what "seeking" means for a reference. A
reference with no offset opens the source at its start, which is what a
document reference has always meant.

For a **citation** — which has `{sourceId, start, end}` and no offset — the
offset is derived: `locators.resolve` over the stored `locator_map`, taking the
first `TimeSpan`. This is the first production caller of that function.

**Ruling: a citation into a source with no locator map renders exactly as it
does today** — a link to the document, no moment. Text sources have no map and
never will, and that is the majority case; a design that treated a missing map
as an error would break every existing citation to make media citations work.

## What this does not do

- **No new events, no new read model, no new column.** A reference is derived at
  render time from data already stored. `locators.resolve`'s docstring makes the
  same point about citations: "a media citation costs no new event and no stored
  offset".
- **No transcript-following player.** Highlighting the transcript line as a
  video plays is a real feature and is not this one; this design makes the
  moment *reachable*, not synchronised.
- **No editing of references.** The model writes them; nobody hand-authors them.

## Testing

- The pre-pass, over: a valid point reference, a valid range, an unknown-but-
  well-formed id, a malformed id, an id containing characters that would change
  the URL's meaning, a reference inside a code fence (which must **not** be
  transformed — a code block showing the syntax is documentation, not a link),
  and a non-integer offset. Every invalid case renders as literal text.
- **A security test that a reference cannot produce an href the allow-list would
  reject**, written as an assertion about the rendered DOM rather than about the
  pre-pass's output — the claim is about what reaches the page.
- Citation → moment: a media citation with a locator map renders a link carrying
  the resolved second; the same citation against a source with no map renders
  today's link unchanged.
- Browser-mode is **not** indicated: nothing here is a computed style or a
  measurement. Roles, rendered text and hrefs belong in jsdom, per `CLAUDE.md`.

## The prompt half, which is easy to forget

None of this happens unless the model knows the syntax exists. The tool prompts
that describe reading a source have to describe referencing one, in the same
place and the same voice. A syntax nothing emits is dead code with tests.
