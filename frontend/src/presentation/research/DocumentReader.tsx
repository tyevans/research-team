import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { Markdown } from '../common/content.tsx'
import { ErrorBox, Loading } from '../common/primitives.tsx'

/** One document's text, read fresh rather than reused from the list row --
 *  `DocumentSummary` carries no `text`, on purpose, so this is the only
 *  place in the pane that ever asks the server for it. */
export const DocumentReader = ({
  projectId,
  sourceId,
}: {
  projectId: ProjectId
  sourceId: SourceId
}) => {
  const { documents } = useContainer()

  const query = useQuery({
    queryKey: queryKeys.document(projectId, sourceId),
    queryFn: () => documents.read(projectId, sourceId, undefined),
  })

  if (query.isPending) return <Loading what="document" />

  if (query.isError) {
    return (
      <ErrorBox
        heading="Could not read this document"
        message={query.error instanceof Error ? query.error.message : String(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const document = query.data

  return (
    // No heading of its own: this renders inside a drawer that already names
    // the document in its header, and two copies of the same title stacked on
    // each other is chrome, not information. The title-or-id fallback moved to
    // the drawer with it, where it is taken from the list row so the heading is
    // right while this component's own fetch is still in flight.
    // Its own padding rather than the drawer's, because this is rendered
    // outside a drawer too. `pb-5` is larger than the top on purpose: prose
    // wants room under its last line where a panel does not.
    //
    // The text gets a measure. Full-width lines across a 640px drawer are the
    // same reason this was hard to read in the old 340px rail, at the other
    // extreme.
    <article className="px-4 pt-[12px] pb-5">
      {document.droppedReason ? (
        <p className="m-0 mb-[8px] text-xs text-k-failure">Dropped: {document.droppedReason}</p>
      ) : null}
      {/* Rendered, not shown raw. The corpus stores markdown -- pages arrive
          converted, and the extraction prompt is written against that -- so a
          `whitespace-pre-wrap` paragraph was showing `##`, `[text](url)` and
          table pipes as literal characters on the one screen whose whole job
          is reading the document.

          **This changes what a document with no markdown in it looks like.**
          `whitespace-pre-wrap` honoured every newline; `marked` runs with
          `breaks: false`, so a single newline inside a paragraph now folds
          into a space and only a blank line starts a new one. For markdown
          that is correct and is the point. For a plain-text source whose line
          breaks were meaningful -- a poem, a log -- it is a regression, and
          the fix if one turns up is a per-document choice about which it is,
          not `breaks: true`, which would break every real markdown document
          instead.

          `md-bare` because the `<article>` above already owns the padding and
          the measure; see `markdown.css`. The measure moves here from the old
          paragraph, unchanged. */}
      <Markdown className="md-bare max-w-[68ch] text-sm leading-[1.65]" source={document.text} />
    </article>
  )
}
