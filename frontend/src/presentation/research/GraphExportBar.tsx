/** Take the drawing away with you.
 *
 * Three plain links rather than a menu or a button that fetches: each one is
 * an `<a download>` at a URL the server answers with a file, so the browser
 * does the download — a progress indicator, a cancel, and the filename from
 * `Content-Disposition`, none of which this console would get for free from a
 * `fetch` into a `Blob`.
 *
 * **The HTML is named first and named differently**, because it is the one a
 * person can open. The other two are for loading the graph somewhere else and
 * read as what they are: file formats. A row that offered "Export" and made
 * the reader choose a format before knowing what any of them did would put the
 * interesting one behind a decision.
 */
export const GraphExportBar = ({
  graphUrl,
  entity,
  entityName,
}: {
  graphUrl: (format: 'html' | 'json' | 'graphml', entityId: string | null) => string
  /** The selected entity, which narrows every link below to its
   *  neighbourhood. Exporting the whole project while looking at one node is
   *  the mismatch worth avoiding: the file that arrives is not the picture the
   *  reader was looking at when they asked for it. */
  entity: string | null
  entityName: string | null
}) => (
  <div className="flex flex-wrap items-center gap-2 rounded-md border border-solid border-line bg-bg-panel p-2 shadow-1">
    <span className="text-xs text-fg-dim">
      {entity === null ? 'Export the graph' : `Export around “${entityName ?? entity}”`}
    </span>
    <a href={graphUrl('html', entity)} download className={LINK}>
      Drawing (.html)
    </a>
    <a href={graphUrl('json', entity)} download className={LINK}>
      .json
    </a>
    <a href={graphUrl('graphml', entity)} download className={LINK}>
      .graphml
    </a>
  </div>
)

/** The same row vocabulary the command bar's buttons use, as a link. `text-fg`
 *  and `no-underline` because a browser's default link colour and underline
 *  are the two things that would make these read as prose rather than as the
 *  controls beside them. */
const LINK = [
  'rounded-md focus-visible:lay-ring-inward border border-solid border-line',
  'bg-bg-panel px-2 py-1 text-xs text-fg no-underline hover:bg-bg-hover',
].join(' ')
