import { useAttempts } from '@application/lesson/use-attempts.ts'
import { useLesson } from '@application/lesson/use-lesson.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { SessionId, type ProjectId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { LessonDocument } from '../lesson/LessonDocument.tsx'

/** One authored course file, rendered as the lesson it is rather than as a
 *  description of one.
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

  if (lesson.interactive && lesson.doc) {
    return (
      <div className={className}>
        <LessonDocument doc={lesson.doc} attempts={attempts} projectId={projectId} />
      </div>
    )
  }

  return <Markdown source={markdown} projectId={projectId} className={className} />
}
