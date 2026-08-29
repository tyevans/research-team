import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { Slide } from '@domain/lesson/slides.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { Component } from './LessonDocument.tsx'

/** One slide, dressed by its kind.
 *
 * **The prose goes through `Markdown` and the widgets through `Component`, the
 * same two the document view uses.** Nothing here re-renders a component: a
 * quiz on a slide is the quiz, mounted, answerable, posting against the same
 * session and path. That is not a nicety -- a deck that drew pictures of its
 * widgets would be a worse artifact than the document it came from, and it is
 * the failure most likely to pass a rendering test, because a widget that
 * renders and cannot be operated looks identical in a snapshot.
 *
 * **The layout is deliberately not centred.** These are paragraphs, not
 * bullets: the corpus's median paragraph is 379 characters, and centred prose
 * at that length is unreadable. Text is left-aligned on a ~62-character measure
 * against the rail, which is where the eye already is.
 *
 * The measure is in `rem` and not in `ch`, which is the obvious unit and the
 * wrong one here: `ch` resolves against the *wrapper's* font, and the wrapper
 * inherits `.md`'s 12px while the slide's own type is set on the descendants at
 * 16-32px. `max-w-[52ch]` on the quote gave a 340px column holding 32px serif,
 * which wrapped every five words. Seen in a screenshot, not derived.
 *
 * **Why the type is written as `[&_p]:` descendant utilities rather than on the
 * `Markdown` element itself.** `markdown.css` gives `.md` a `font-size`, a
 * `line-height` and `padding: 10px 14px 40px`, all unlayered -- so a `text-`,
 * `leading-` or `p-0` utility on that element is inert, which is CLAUDE.md's
 * unlayered-rule trap again. Measured, not reasoned: the first screenshot of
 * the title slide had 12px body text indented 14px past its own heading, with
 * every intended utility present in the class attribute.
 *
 * Two things together are the fix. `.doc` on the wrapper turns `.md-unwrapped`
 * into `display: contents` (`structure.css`), so the padded box stops existing
 * rather than being fought; and the type lands on the descendant elements,
 * where the only thing to beat is inheritance.
 *
 * **The selectors are `p` and `blockquote`, not `.md-p` and `.md-quote`, and
 * that was a surprise worth writing down.** `renderMarkdown` adds a class to
 * exactly one kind of node -- links -- so the `.md-p`, `.md-quote`, `.md-list`
 * and `.md-h` rules in `markdown.css` match nothing that renderer produces.
 * The first draft of this file targeted them and every utility was silently
 * inert; the quote slide rendered at body size with a UA `blockquote` indent.
 * Found in a screenshot, which is the only place it was visible. Not fixed
 * here -- a stylesheet full of rules that match nothing is its own piece of
 * work -- but it is why these selectors look lower-level than the ones beside
 * them elsewhere in the tree.
 */
export const SlideView = ({
  slide,
  attempts,
  withheldExplanation,
  projectId,
}: {
  slide: Slide
  attempts: AttemptsApi
  withheldExplanation: string
  projectId?: ProjectId
}) => {
  if (slide.kind === 'title') {
    return (
      <div className="deck-title flex h-full flex-col justify-center gap-5">
        <h1 className="m-0 max-w-[18ch] font-serif text-[clamp(30px,4.4vw,58px)] leading-[1.08] font-normal text-fg">
          {slide.title}
        </h1>
        {/* A directional width with `border-0` beside it, never `border-solid`
            with a directional width alone -- see CLAUDE.md. */}
        <div className="w-[72px] border-0 border-t-2 border-solid border-accent" />
        {slide.text ? <Prose text={slide.text} dim {...(projectId ? { projectId } : {})} /> : null}
      </div>
    )
  }

  if (slide.kind === 'quote') {
    return (
      <div className="deck-quote flex h-full flex-col justify-center gap-6">
        <SectionHead slide={slide} />
        {/* The hanging bracket, and the risk this design takes: a passage in
            serif at 2.4x with no quotation marks, marked as quoted by the
            bracket and by the citation `Markdown` renders under it. It is the
            one slide kind that looks unlike the rest of the console, and it is
            the one that earns it -- a cited passage is the load-bearing
            material of every lesson here.
            `[&_.md-quote]:border-0` undoes `markdown.css`'s own left rule, so
            the bracket is drawn once and by this file. */}
        <div className="doc max-w-[42rem] [&_blockquote]:my-0 [&_blockquote]:ml-0 [&_blockquote]:border-0 [&_blockquote]:border-l-[3px] [&_blockquote]:border-solid [&_blockquote]:border-accent [&_blockquote]:py-1 [&_blockquote]:pl-6 [&_p]:m-0 [&_p]:font-serif [&_p]:text-[clamp(19px,2.3vw,32px)] [&_p]:leading-[1.4] [&_p]:text-fg">
          <Markdown
            source={slide.text}
            className="md-unwrapped"
            {...(projectId ? { projectId } : {})}
          />
        </div>
      </div>
    )
  }

  if (slide.kind === 'component') {
    return (
      <div className="deck-component flex h-full flex-col justify-center gap-6 overflow-y-auto">
        <SectionHead slide={slide} />
        <div className="w-full max-w-[46rem]">
          <Component
            block={slide.block}
            attempts={attempts}
            withheldExplanation={withheldExplanation}
            {...(projectId ? { projectId } : {})}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="deck-prose flex h-full flex-col justify-center gap-6 overflow-y-auto">
      <SectionHead slide={slide} />
      <Prose text={slide.text} {...(projectId ? { projectId } : {})} />
    </div>
  )
}

/** The section's name, at full weight, on the slide that opens it.
 *
 * Once per section and not once per slide: a continuation carries the name
 * small in the deck's eyebrow instead, so a reader who joins mid-section still
 * knows where they are without every slide shouting the same heading. That
 * split is `opensSection`, decided in the segmenter -- see `railRows`, which
 * reads the same field so the rail and the stage cannot disagree about where a
 * section starts. */
const SectionHead = ({ slide }: { slide: Slide }) =>
  slide.opensSection && slide.section !== null ? (
    <h2 className="deck-section m-0 max-w-[26ch] font-serif text-[clamp(21px,2.2vw,30px)] leading-[1.15] font-normal text-fg">
      {slide.section}
    </h2>
  ) : null

/** A slide's prose at slide size. `dim` is the title slide's lead paragraph,
 *  which sits under a 58px heading and should not compete with it. */
const Prose = ({
  text,
  projectId,
  dim = false,
}: {
  text: string
  projectId?: ProjectId
  dim?: boolean
}) => (
  <div
    className={
      dim
        ? 'doc max-w-[34rem] [&_p]:mt-0 [&_p]:mb-4 [&_p]:text-[clamp(14px,1.1vw,17px)] [&_p]:leading-[1.7] [&_p]:text-fg-dim'
        : 'doc max-w-[36rem] [&_li]:mb-2 [&_li]:text-[clamp(14px,1.1vw,17px)] [&_p]:mt-0 [&_p]:mb-4 [&_p]:text-[clamp(14px,1.1vw,17px)] [&_p]:leading-[1.75] [&_p]:text-fg [&_ul]:pl-5'
    }
  >
    <Markdown source={text} className="md-unwrapped" {...(projectId ? { projectId } : {})} />
  </div>
)
