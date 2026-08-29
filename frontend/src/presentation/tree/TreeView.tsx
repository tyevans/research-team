import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { SORT_LABELS, SORTS, type Sort } from '@domain/project/board.ts'

import { Button } from '../common/primitives.tsx'
import { DriftBanner } from './DriftBanner.tsx'
import { NewProjectForm } from './NewProjectForm.tsx'
import { ProjectBoard } from './ProjectBoard.tsx'
import { useSessionForest } from './SessionTree.tsx'

/** The console's front door: every project, and how far each one has got.
 *
 * **What was wrong with the page this replaces.** It listed projects and
 * showed, for each, a session count, a file count, a relative time and the
 * first message of one session. None of those is a fact about a project. The
 * file count was documented as the *sum of per-session* live-file counts, so a
 * path two sessions touched was counted twice. The time was the newest session
 * *start* — `landing.ts` warned in a comment that a row "must not claim it is"
 * the last activity — and measured against the real database it was up to
 * 1h24m stale. And the session preview, which was the largest text on every
 * row, was a generated authoring prompt: four of six projects opened with the
 * identical sentence, so the most prominent thing on the page was the same
 * string repeated down it.
 *
 * The result was six rows that differed in a name and two meaningless numbers,
 * at roughly 170px each, on a 1440px viewport using about a fifth of its
 * width. A project here has sources, topics, a knowledge graph, a curriculum
 * and a course catalog, and none of that was on the index.
 *
 * **What replaces it** is a board: one row per project carrying the pipeline
 * the system actually runs — topics, sources, extraction, courses — with the
 * bars scaled across the whole board so the rows form columns and the
 * comparison is readable without digits. See `ProjectPipeline`.
 */
export const TreeView = () => {
  const { projects } = useContainer()
  const scrollRef = useRef<HTMLElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<Sort>('recent')
  const [creating, setCreating] = useState(false)

  const projectsQuery = useQuery({
    queryKey: queryKeys.projects(),
    queryFn: () => projects.list(),
  })
  const { all: sessionRows, isPending: sessionsPending } = useSessionForest()

  // `/` focuses search, the way it does in every other list-shaped tool. Only
  // when the reader is not already typing somewhere: a `/` in the search box,
  // or in the project-name field, is a character and not a shortcut.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return
      const active = document.activeElement
      if (active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement) return
      event.preventDefault()
      searchRef.current?.focus()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  /** Nothing exists at all — so the whole page becomes the answer, rather than
   *  an empty board under a search box. Both reads have to have answered: an
   *  empty page shown while the queries are still in flight would tell a
   *  returning user their work is gone. */
  const firstRun =
    !projectsQuery.isPending &&
    !projectsQuery.isError &&
    projectsQuery.data.length === 0 &&
    !sessionsPending &&
    sessionRows.length === 0

  if (firstRun) return <FirstRun />

  return (
    <section className="view view-home" ref={scrollRef}>
      {/* The scroll container is the section, so the virtualizer measures
          against the whole page; the width lives on the wrapper inside it. */}
      <div className="home-inner">
        <div className="actions">
          <Button tone="accent" onClick={() => setCreating(!creating)} aria-expanded={creating}>
            + New project
          </Button>
          <input
            ref={searchRef}
            type="search"
            className="input actions-search"
            placeholder="find a project  ( / )"
            aria-label="Find a project by name"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            // Escape clears and gives the page back, which `type="search"`
            // gives you in WebKit and in no other engine — and even there only
            // as a clear, leaving focus in a box the reader has finished with.
            onKeyDown={(event) => {
              if (event.key !== 'Escape') return
              event.preventDefault()
              setSearch('')
              searchRef.current?.blur()
            }}
          />
          <SortControl sort={sort} onSort={setSort} />
        </div>

        {creating ? <NewProjectForm onCreated={() => setCreating(false)} /> : null}

        {/* In the page, not only as a badge in the topbar: every row's counts
            come out of projections, so "the projection may be behind" is a
            statement about everything below this line. */}
        <DriftBanner />
        <ProjectBoard scrollRef={scrollRef} search={search} sort={sort} />
      </div>
    </section>
  )
}

/** Three orderings, as radio buttons rather than a `<select>`.
 *
 * Three is few enough that a dropdown hides two of them behind a click to
 * learn what the options even are, and this is a control a reader is expected
 * to try rather than to configure once.
 *
 * `role="radiogroup"` over real radios rather than buttons with
 * `aria-pressed`: exactly one is chosen at a time and the arrow-key roving
 * that a radio group gets for free is the behaviour wanted. The inputs are
 * visually hidden and the labels are the control — which is the arrangement
 * that keeps the native keyboard semantics without styling an `appearance:
 * none` input.
 *
 * **The chosen tone reads the input's own state rather than a second copy of
 * it.** `peer-checked:` is a sibling selector on the real `:checked`, so the
 * drawing and the state cannot disagree — where a class computed from the
 * `sort` prop would be a second representation of the same fact, free to drift
 * from the first. CLAUDE.md records a defect of exactly that shape: a
 * `Tooltip` and a `RadioGroup` both writing `data-state` to one element, so a
 * chosen control drew in the unchosen colour past a fully green suite.
 */
const SortControl = ({ sort, onSort }: { sort: Sort; onSort: (sort: Sort) => void }) => (
  // One hairline box with three segments inside it, so it reads as one control
  // with three states rather than as three buttons. `overflow-hidden` clips the
  // children to the box's radius, which is why no child sets one.
  <div
    className="flex items-stretch overflow-hidden rounded-md border border-line bg-bg-panel"
    role="radiogroup"
    aria-label="Order projects by"
  >
    {SORTS.map((option, index) => (
      <label key={option} className="flex">
        {/* `sr-only` rather than `hidden`, and the difference is the whole
            reason this is a radio group at all: `display:none` and
            `visibility:hidden` remove the input from the accessibility tree,
            taking the group's roving arrow-key behaviour with it — and the
            control would still *look* right, because the labels are what is
            drawn. The failure would be invisible to everything but a keyboard.

            `peer` is what lets the sibling span read this input's checked and
            focus state. A peer selector rather than a class the component
            computes from `sort`, so the DOM cannot disagree with the input's
            own state: they are the same fact. CLAUDE.md records a defect of
            exactly the other shape — two libraries writing `data-state` to one
            element, so a chosen control drew in the unchosen colour past a
            fully green suite. */}
        <input
          type="radio"
          name="project-sort"
          className="peer sr-only"
          value={option}
          checked={sort === option}
          onChange={() => onSort(option)}
        />
        <span
          className={clsx(
            'block cursor-pointer px-3 py-2 font-mono text-xs text-fg-dim select-none',
            'hover:bg-bg-hover hover:text-fg',
            'peer-checked:bg-accent peer-checked:text-accent-fg',
            // The ring is drawn on the label because the input it belongs to is
            // a clipped 1px box nobody can see.
            'peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:-outline-offset-2 peer-focus-visible:outline-accent',
            // A hairline between segments, on every label after the first. A
            // directional width with no `border-solid` beside it, which is the
            // form CLAUDE.md endorses — the shorthand would give the other
            // three sides a style with no width and draw a box.
            index > 0 && 'border-l border-line',
          )}
          data-sort-label={option}
        >
          {SORT_LABELS[option]}
        </span>
      </label>
    ))}
  </div>
)

/** The empty database, as a page rather than an empty board.
 *
 * What somebody who has just cloned this and typed `uv run web.py` needs, in
 * order: that it is alive and connected (the topbar's badge, already correct),
 * a sentence saying what this is, what the thing they are about to make will
 * fill up with, and one action.
 *
 * **The pipeline is taught here rather than only drawn on the board.** The
 * four stages are the vocabulary every row uses, and a first-time reader has
 * no way to infer from three unlabelled bars that "sources" arrive by
 * investigating "topics". Four lines of prose on the one screen where somebody
 * is genuinely reading is the cheapest place that explanation can live — it
 * costs a returning reader nothing, because they never see this page again.
 */
const FirstRun = () => (
  <section className="view view-home view-first-run">
    <div className="first-run">
      <p className="purpose">
        An agent whose whole session is one event log: every message, tool call and file write, in
        order. Scrub it back, fork it, and pick it up later.
      </p>
      <p className="purpose">
        A project is where work outlives one conversation — a filesystem and a knowledge graph its
        sessions share.
      </p>

      {/* `list-decimal` rather than the default disc: the stages are a genuine
          sequence — each consumes the one before it — so the numbering encodes
          something true rather than decorating a list. */}
      <ol className="mb-5 max-w-[78ch] list-decimal pl-5 text-sm text-fg-dim">
        <li className="mb-2">
          <b className="font-semibold text-fg">Topics</b> — the questions the project is trying to
          answer. Seed them from a subject, or write your own.
        </li>
        <li className="mb-2">
          <b className="font-semibold text-fg">Sources</b> — what investigating a topic fetches and
          keeps.
        </li>
        <li className="mb-2">
          <b className="font-semibold text-fg">Graph</b> — the entities and relationships extracted
          from those sources.
        </li>
        <li className="mb-2">
          <b className="font-semibold text-fg">Courses</b> — what the catalog builds out of the
          graph.
        </li>
      </ol>

      <NewProjectForm />

      <p className="first-run-aside">
        Prefer a terminal? Run <code>uv run main.py</code> — both front ends share one database.
      </p>
    </div>
  </section>
)
