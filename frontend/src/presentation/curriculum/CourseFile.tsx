import { useAttempts } from '@application/lesson/use-attempts.ts'
import { useLesson } from '@application/lesson/use-lesson.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { SessionId, type ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { Button } from '../common/primitives.tsx'
import { Deck } from '../lesson/Deck.tsx'
import { FILE_WITHHELD_EXPLANATION, LessonDocument } from '../lesson/LessonDocument.tsx'
import { withDeck } from '../routing/routes.ts'
import { navigate, useDeck } from '../routing/use-route.ts'

/** One authored course file, rendered as the lesson it is rather than as a
 *  description of one -- and, since the slideshow, in either of two readings.
 *
 * **The defect this closes.** `CourseUnit` handed the authoring turns' markdown
 * straight to `<Markdown>`, which is correct for prose and wrong for the one
 * thing a lesson is for: a ```component:mcq``` fence is not markdown, so
 * `renderMarkdown` did the only thing it can with an unknown info string and
 * printed the widget's yaml as a code block. Measured in Chromium on
 * 2026-08-24 against `/course/resolution`: 19 `<pre><code
 * class="language-component:*">` blocks and **zero** `section.cmp` widgets --
 * 10 of them in the unit and 3 in each of the three lessons. Every other
 * surface that shows a widget (`FileView`, `TopicDocuments`, `AskTurn`,
 * `DialogueExchange`) goes through `LessonDocument`; the course page was the
 * only one that did not, which is exactly why the same widget worked
 * everywhere else.
 *
 * **Why a second request per file rather than parsed blocks on the course
 * payload.** The parse is deliberately server-side -- `domain/lesson/document.ts`
 * says so and gives the reason: the learner projection strips the answer key on
 * the server, so the browser genuinely cannot grade. Adding a parsed form to
 * `read_course_unit` would have meant a second place deciding what a learner is
 * allowed to see, and the two could drift apart on exactly the field that
 * matters. Going through `/files/parsed` reuses the one projection every other
 * reader already trusts, and it is also what makes the widgets *work* rather
 * than merely draw: an attempt posts against a session and a path, which is the
 * same pair this asks the parse with.
 *
 * The cost is real and accepted: one request per lesson plus one for the unit
 * -- four on this course -- against a payload that has already arrived.
 *
 * **`learner`, not `author`.** This is where somebody reads the course, so the
 * answer key is withheld and graded on the server: the same call `FileView`
 * makes when its audience toggle is set to learner. There is no toggle here on
 * purpose -- a course page that can reveal its own answers is not a course page.
 *
 * **The fallback is the old behaviour, deliberately.** `useLesson` reports
 * `interactive: false` both for a file with no widgets and for a parse that
 * failed, and a unit of pure prose is a real case -- so a file with nothing to
 * operate renders through `Markdown` exactly as it did before, and a parse
 * failure costs the reader the widgets and nothing else. An error banner over a
 * course that reads perfectly well would be noise. The cost of folding the two
 * together is that a parse outage is invisible here; the file viewer makes the
 * same trade, for the same reason.
 *
 * **The deck.** "Present" opens the same parsed document as slides, over the
 * page, at `?deck=<path>`. Three things about that are decisions rather than
 * conveniences, argued in `docs/design/lesson-slideshow.md`: the slides are
 * *derived* from the document rather than authored, so every lesson ever
 * written has one; the position is in the URL, so a slide is a link somebody
 * can send; and the document below stays exactly as it was, because it is the
 * accessible baseline and the deck is an equal reading rather than a
 * replacement.
 *
 * The button is gated on the *parse* rather than on `interactive`: a lesson of
 * pure prose presents perfectly well and has no widgets, so gating on widgets
 * would have hidden the deck on the one kind of file it most obviously suits.
 * A file whose parse failed has no blocks to segment, so there the button is
 * absent and the prose renders -- the same trade the paragraph above describes,
 * and the reason the early return moved from `interactive` to `doc`.
 */
export const CourseFile = ({
  projectId,
  sessionId,
  path,
  markdown,
  className,
}: {
  projectId: ProjectId
  sessionId: string
  path: string
  markdown: string
  className: string
}) => {
  const session = SessionId(sessionId)
  const filePath = FilePath.of(path)
  const at = ScrubPoint.head()

  const lesson = useLesson(session, filePath, 'learner', at, true)
  const attempts = useAttempts(session, filePath, at)
  const { deck, hash } = useDeck()

  const presenting = deck !== null && deck.path === path

  // No parse at all: the old path, unchanged, and no deck -- there are no
  // blocks to segment. A parse *that succeeded and found no widgets* is a
  // different case and keeps both: the document renders as plain markdown
  // exactly as it did before, and it still presents.
  if (lesson.doc === null || lesson.doc.blocks.length === 0) {
    return <Markdown source={markdown} projectId={projectId} className={className} />
  }

  return (
    <div className={className}>
      <Button
        small
        tone="quiet"
        className="mb-2"
        onClick={() => navigate(withDeck(hash, { path, slide: 0 }))}
      >
        Present this lesson
      </Button>
      {lesson.interactive ? (
        <LessonDocument doc={lesson.doc} attempts={attempts} projectId={projectId} />
      ) : (
        <Markdown source={markdown} projectId={projectId} />
      )}
      {presenting ? (
        <Deck
          doc={lesson.doc}
          attempts={attempts}
          label={path.split('/').at(-1) ?? path}
          withheldExplanation={FILE_WITHHELD_EXPLANATION}
          projectId={projectId}
          slide={deck.slide}
          // `replace`, for the reason scrubbing uses it: arrowing through
          // thirty slides must not leave thirty entries in the back stack, and
          // the position must still be in the URL because a slide is a linkable
          // thing.
          onSlide={(index) => navigate(withDeck(hash, { path, slide: index }), { replace: true })}
          onClose={() => navigate(withDeck(hash, null), { replace: true })}
        />
      ) : null}
    </div>
  )
}
