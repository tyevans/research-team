import { useState } from 'react'

/** What one sweep has done so far, as counts rather than as a list.
 *
 * `declined` is separate from `barren` because the server keeps them separate,
 * and that distinction is the only reason this summary is worth rendering:
 * `found: null` is a document that was **not read** -- over the size ceiling,
 * or an unreadable reply -- and it is still pending, where `found: 0` was read
 * and states no classes and is finished. Collapsing the two would report a
 * corpus as fully grouped when part of it was refused, which is precisely the
 * silence the `ontology_examined` table exists to break.
 */
export type SweepProgress = {
  readonly done: number
  readonly total: number
  readonly found: number
  readonly barren: number
  readonly declined: number
}

/** How a press of the sweep should read the corpus.
 *
 * Two independent axes, and they are separate because they answer different
 * questions. `again` is *which documents* -- the unread ones, or every
 * extracted one including those a pass has already retired. `lenient` is *what
 * counts as a class* once a document is being read.
 *
 * They are usually pulled together, because the reason to re-read a document
 * that was recorded as barren is usually that the strict pass refused
 * something. They are still not one flag: a lenient first pass over a fresh
 * corpus is legitimate, and so is re-reading everything strictly against a
 * model that has since been changed.
 */
export type SweepRequest = {
  readonly again: boolean
  readonly lenient: boolean
}

/** Read every ungrouped document for the classes it states.
 *
 * **Why a person has to press this, and why the pane was empty without it.**
 * The discovery route, the repository method and `DocumentExtractor.ungrouped`
 * all existed before this control did, with tests on each and nothing driving
 * any of them -- so the ontology pane's empty state instructed a reader to
 * "run a discovery pass" using a button that had never been built, on a
 * corpus where `ontology_examined` was empty because no pass had ever run.
 *
 * **Sequential, not concurrent.** Each document is one model call over its
 * whole text, and the ceiling is 500,000 characters; `ontology_discovery.py`
 * records a measured case of a 19,644-character prompt not returning within
 * 500 seconds against a local model. Thirty-seven of those in parallel is a
 * serving stack falling over rather than a faster sweep.
 *
 * **A second press can read what the first one already retired.** "Read every
 * document again" lifts the one exclusion a pass can be wrong about: a
 * document is recorded as examined whether it stated no classes or stated some
 * the verifier refused, and only the first of those is finished. Measured
 * 2026-08-24 on the owner's corpus, both examined documents rendered as "states
 * no classes" and one of them had a real class dropped for a quote that spanned
 * a line wrap. Without this control there was no way back to it from the
 * console at all.
 *
 * **The lenient checkbox is the other half and is deliberately not the same
 * control.** Re-reading strictly is worth having on its own -- the model is not
 * deterministic, and it may have been changed since. Reading leniently stops
 * checking that the document states the class at all, which is a claim a reader
 * has to opt into rather than get for pressing a button labelled "again".
 *
 * **Nothing resumes it.** Closing the tab stops the sweep where it stands,
 * and that is acceptable only because pressing again is safe: an examined
 * document drops off the work list, so a second press reads what the first
 * one did not reach rather than paying for it twice. A server-side queue
 * would survive the tab, and is deliberately not built -- `discover_ontology`
 * records why it cannot reuse `ExtractionQueue`, and a second queue is not a
 * bounded change.
 */
export const DiscoverySweep = ({
  pending,
  running,
  progress,
  error,
  onRun,
}: {
  /** The work list, or `null` while it is still being read. Empty is a real
   *  answer and the one this component treats as finished -- the server
   *  answers 503 rather than an empty list when discovery is unwired, so an
   *  empty list here can be trusted. */
  pending: readonly string[] | null
  running: boolean
  progress: SweepProgress | null
  error: string | null
  onRun: (request: SweepRequest) => void
}) => {
  /** Held here rather than in the pane: it is a setting of this control, read
   *  only when a button in it is pressed, and lifting it would make the pane
   *  re-render on a checkbox. */
  const [lenient, setLenient] = useState(false)

  if (pending === null) return null

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg-panel p-3">
      <p className="m-0 min-w-0 flex-1 text-xs text-fg-dim">
        {pending.length === 0 ? (
          <>
            Every extracted document has been read for the classes it states. A document that states
            none is read once and stays read, so this stays empty until the corpus grows — but
            &ldquo;states none&rdquo; also covers a class the reading refused, which is what reading
            again is for.
          </>
        ) : (
          <>
            {pending.length} extracted {pending.length === 1 ? 'document has' : 'documents have'}{' '}
            not been read for the classes they state. Each is one model call over the whole
            document, so this takes a while and has to stay open.
          </>
        )}
      </p>
      {pending.length > 0 && (
        <button
          type="button"
          onClick={() => onRun({ again: false, lenient })}
          disabled={running}
          className="focus-visible:lay-ring-inward shrink-0 rounded-md border border-line bg-bg-raise px-2 py-1 text-xs text-fg hover:bg-bg-hover disabled:opacity-60"
        >
          {running
            ? `Reading ${progress ? `${progress.done} of ${progress.total}` : '…'}`
            : `Read ${pending.length} ${pending.length === 1 ? 'document' : 'documents'}`}
        </button>
      )}
      {/* Always offered, including with documents still pending: a reader who
          has just changed the checkbox wants the whole corpus read under it,
          not only the part no pass has reached. The count is deliberately
          absent from the label -- this component is handed the *pending* list
          and does not know how many extracted documents there are, and a
          number guessed from the wrong list would be worse than none. */}
      <button
        type="button"
        onClick={() => onRun({ again: true, lenient })}
        disabled={running}
        className="focus-visible:lay-ring-inward shrink-0 rounded-md border border-line px-2 py-1 text-xs text-fg-dim hover:bg-bg-hover disabled:opacity-60"
      >
        Read every document again
      </button>
      <label className="flex shrink-0 cursor-pointer items-center gap-2 text-xs text-fg-dim">
        <input
          type="checkbox"
          checked={lenient}
          disabled={running}
          onChange={(event) => setLenient(event.target.checked)}
          className="focus-visible:lay-ring-inward accent-accent"
        />
        {/* Says what stops being checked, not what is gained. A label reading
            "find more classes" would be an accurate description of the effect
            and a dishonest one of the trade: what this gives up is the only
            evidence that the document groups these members at all. */}
        Keep a class whose members are in the document even if the sentence quoted for it is not
      </label>
      {progress !== null && !running && (
        <p className="m-0 w-full text-xs text-fg-dim">
          {/* Three counts rather than one, and never a bare "done": a sweep
              that read nothing and a sweep that found nothing look identical
              from a success message, and only one of them is worth retrying. */}
          {progress.found > 0
            ? `${progress.found} ${progress.found === 1 ? 'document' : 'documents'} stated classes.`
            : 'No document stated a class.'}{' '}
          {progress.barren > 0 && `${progress.barren} states no classes. `}
          {progress.declined > 0 && (
            <span className="text-k-warning">
              {progress.declined} was not read — too long, or the reply could not be used. Those
              stay on the list and can be tried again.
            </span>
          )}
        </p>
      )}
      {error !== null && (
        <p className="m-0 w-full text-xs text-k-failure">
          {/* The sweep stopped here; what it had already read is kept, because
              each document is recorded as examined by its own pass rather than
              at the end. */}
          {error} Documents already read are kept — press again to carry on.
        </p>
      )}
    </div>
  )
}
