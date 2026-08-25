# Course widgets rendered as their own source

Diagnosis and fix, 2026-08-24, branch `worktree-agent-abadb89cff560dd16`,
based on `main` at d9be87a.

Claims are marked **traced** (followed through the code, deterministic),
**measured** (observed from a running system), or **inferred** (consistent with
the symptom, with a step this investigation could not close). The vocabulary is
`docs/design/broken-widgets-findings.md`'s, and that document is answered at
the end.

---

## The symptom

Interactive lesson widgets did not render on the realized-course page. The same
widgets were known good elsewhere.

Reference URL:
`http://localhost:8000/#/p/6e7bd68f-68e6-422f-a11d-3c2e4612de55/course/resolution`

**Measured**, in Chromium against that page on the pre-fix build:

| | count |
|---|---|
| `<pre><code class="language-component:*">` inside `.crs-course-text` | **19** |
| `section.cmp` (a rendered widget) | **0** |
| of the 19, in `.crs-course-unit` | 10 |
| of the 19, in the three `.crs-course-lesson`s | 3 each |

The widgets were not degraded, not `unavailable`, and not empty. Their yaml
source was printed on the page as a code block.

## The cause

**Traced.** `CourseUnit.tsx` passed the authoring turns' markdown to
`<Markdown>` from `presentation/common/content.tsx`. That component is
`renderMarkdown` plus DOMPurify, and it is correct for prose. A widget is not
prose: it is a fenced block whose info string is `component:mcq`, and the only
thing a markdown renderer can do with an info string it does not know is emit
`<pre><code class="language-component:mcq">` holding the fence body verbatim.
Nothing threw, nothing logged, and the page rendered 200.

**Traced.** Every other surface that shows a widget renders through
`presentation/lesson/LessonDocument.tsx`, over a document the *server* parsed:

- `presentation/session/FileView.tsx:205`
- `presentation/research/TopicDocuments.tsx:199`
- `presentation/ask/AskTurn.tsx:42`
- `presentation/dialogue/DialogueExchange.tsx:76`

`CourseUnit` was the only widget-bearing surface that did not. That is exactly
why the user's framing was right: same widget, works elsewhere, broken here —
and it is a rendering-context difference, not a bad payload.

**Traced.** The parse is deliberately server-side; `domain/lesson/document.ts`
says so and gives the reason — the learner projection strips the answer key on
the server, so the browser genuinely cannot grade. The parse route is
`GET /api/sessions/{id}/files/parsed`, keyed on a session id **and a path**.

**Traced.** `read_course_unit` in `app.py` returned each lesson's workspace
path but only the unit's *text*. So even a client that wanted to parse the
files had no path to ask for the unit with — and on the measured course that is
10 of the 19 blocks.

### Why no test caught it

**Traced.** `CoursePage.test.tsx` covers the course text thoroughly, and every
one of its assertions is about the three *states* — `authored`, `authoring`,
`unauthored` — and the prose that distinguishes them. Not one fixture contains
a component fence, so no test could tell a rendered widget from its source. The
default `aText()` is `unauthored`, deliberately, "because it is the state that
renders one line and asserts nothing" — which is a good reason that also means
the widget path was never exercised.

This is CLAUDE.md's port-with-one-adapter shape once more, with the seam moved:
the widget renderers were tested against hand-built documents, the course page
was tested against markdown with no widgets in it, and the question "does the
course page put its files through the renderer that draws widgets" was never
asked by anything.

## The fix

`frontend/src/presentation/curriculum/CourseFile.tsx` — new. Given a session id
and a workspace path it calls the same `useLesson` + `useAttempts` pair
`FileView` does, asks for the **learner** projection, and renders through
`LessonDocument`. A file with no components, or a parse that fails, falls back
to `<Markdown>` — the previous behaviour exactly.

`CourseUnit.tsx` routes the unit and every lesson through it.

`read_course_unit` gains `unitPath`, carried through the DTO, the mapper and
the domain `CourseText`.

### What was rejected

**Parsed blocks on the course payload.** One request instead of four, and it
was rejected: it would put a second decision about what a learner may see
beside the one in `project()`, and the two could drift apart on exactly the
field that must not — the answer key. Going through `/files/parsed` reuses the
one projection every other reader already trusts. It is also what makes the
widgets *work* rather than merely draw, since an attempt posts against the same
session-and-path pair.

The cost is stated and accepted: one extra request per course file — four on
the measured course — against a payload that has already arrived.

**`author` as the audience.** Rejected: the course page is where somebody reads
the course. There is no audience toggle here on purpose; a course page that can
reveal its own answers is not a course page.

## What the regression test pins

`frontend/src/presentation/curriculum/CourseUnit.widgets.test.tsx`, three tests:

1. **The widget rendered.** Two `mcq component` regions (the unit and its
   lesson), each with its options as real controls, and `id: res-uu1-mcq` — the
   yaml — absent from the document. Not "nothing threw": the old path threw
   nothing at all and drew 19 code blocks.
2. **The projection asked for is `learner`**, for both files, by path. A page
   that asked as `author` would render identically and ship the key.
3. **A failed parse falls back to prose**, asserted by the prose being present
   rather than by an error box being absent.

`waitFor` rather than `findAllBy` in 1 and 2, and it matters: `findAllBy`
resolves on the first match and passed at one widget while the unit was still
raw — the exact half-fix the test exists to catch.

**Proved red before trusted green.** With the `LessonDocument` branch disabled
in place (no `git checkout`, per CLAUDE.md), tests 1 and 2 fail and test 3
passes — which is right, since the fallback is the old behaviour.

`tests/interfaces/test_course_unit_route.py` asserts `unitPath` equals the
unit's path, by value. A `None` there would put the console silently back on the
prose fallback.

## Measured after the fix

Same page, same course, my worktree's build served on port 8123 against the
real `~/.research-team/sessions.db`:

| | before | after |
|---|---|---|
| `section.cmp` | 0 | **19** |
| `code.language-component:*` | 19 | **0** |

By type: 7 mcq, 4 cloze, 4 definition, 2 compare, 1 flashcards, 1 graph. The
mcq regions carry "answers withheld", so the learner projection is doing its
job on the real payload and not only in the fixture.

---

## What this says about `broken-widgets-findings.md`

That document named two defects in the **authoring** path and was explicitly a
lead rather than an answer. Both are real; **neither accounts for the symptom**,
and the evidence is direct.

**Measured** on the reference course, after the fix: **zero** occurrences of
"(empty file)" anywhere on the page, and **zero** entity references drawing a
raw uuid. Defect 2 is not manifesting here at all, and defect 1's uuid arm is
not either — the entity references on this course carry real names.

Two of that document's own statements are worth updating. It said no course
artifact survived in the database to read, and that no claim in it was
measured; the `resolution` course is such an artifact and was read here. And
its reproduction of defect 2 depends on a padded `compare` cell reaching
`Prose` with `''` — on this course the compare tables have *no* cells at all
(below) and print nothing rather than "(empty file)", so the padded-cell path
is **not confirmed** by this observation either way.

## What I did NOT verify

- **That a widget on the course page can be operated end to end.** The
  measurement is that the widget renders and that the learner projection
  withheld the key. An mcq was not answered against the server from the course
  page. The attempt path is the same `useAttempts(session, path, at)` every
  other surface uses and the pair it is given is the same pair the parse
  succeeded with, so this is **inferred**, not measured. A browser test posting
  one attempt from the course page would close it.
- **Any course other than `resolution`.** One course, one project.
- **A path-file course** (`is_path_file` true — the path overview rather than
  an area). `unitPath` is `path_file(slug)` there, **traced** but not measured;
  no such course was in the database.
- **The full suites.** Per this repo's practice I ran the touched tests
  (`tests/interfaces/test_course_unit_route.py`, and the frontend
  `presentation/curriculum` and `infrastructure/http` suites — 165 tests),
  both ruff gates repo-wide, typecheck, lint and format. CI runs the rest.

## Should be hooked up and is not

Three things, all made visible *by* the fix — they were unobservable while
nothing rendered, which is the point.

1. **The authoring model writes `values:` where the `compare` schema says
   `cells:`, and nothing complains.** **Measured** in the reference course's
   unit: every row of both compare tables is `label` plus `values`. `cells` is
   `Spec(string_list(minimum=0))` and not required (`components.py:1189`), so an
   absent `cells` validates, an unknown `values` is dropped, and the reader gets
   a complete comparison table with **every cell blank** and no error panel.
   This is the same class as `broken-widgets-findings.md`'s defect 1 — the
   course-authoring prompt is thin on the widget schema — and it is a stronger
   case for the `warn` hook that document recommends, because here the model had
   the right idea and the wrong field name. **Not fixed here**: it is an
   authoring defect with a different owner, and the symptom this task was given
   is the rendering one.

2. **A stale-widget hazard on re-authoring.** `CourseUnit` polls
   `courseText` every 3s while `state === 'authoring'`, but the parsed documents
   are separate queries keyed on session and path, and nothing invalidates them
   when the course text changes. **Inferred** — not reproduced: a re-author that
   rewrites a lesson in place would show new prose from the poll and widgets
   from the previous parse until the cache expires. Worth an
   `invalidateQueries` on the lesson keys when `courseText` returns new content.

3. **The `unavailable` and `errors` states on this page reach nobody who can
   act.** A course whose widgets degrade renders the degradation to a *learner*,
   who did not author it and cannot fix it. On the measured course, "Freytag's
   Pyramid — not in this project's graph" is correct degradation of a genuinely
   missing entity, and it is also a health signal about the authoring run that
   no surface aggregates. This is CLAUDE.md's "the number was on screen the
   entire time" waiting to happen again: a per-course count of degraded widgets,
   asserted somewhere, would turn it from a thing a reader notices into a thing
   the system knows.

A fourth, and it is **environment, not a defect**: the four `definition` widgets
answered 500 from `/graph/entities/{id}/definition`, and the traceback is
`openai.APIConnectionError` — my second server used the default model endpoint,
which is dead. The widgets degraded correctly to "could not be defined just
now". Nothing to fix.
