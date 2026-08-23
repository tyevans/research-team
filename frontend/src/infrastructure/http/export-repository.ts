import type {
  CourseExportFormat,
  ExportRepository,
  GraphExportFormat,
  GraphExportScope,
} from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { query, seg } from './http-client.ts'

/** URLs rather than bodies, and that is the whole of this adapter.
 *
 * Every other repository here fetches, parses and maps. This one hands back a
 * string, because the thing on the other end is a *download*: the browser's
 * own `<a download>` streams it straight to disk with a progress indicator, a
 * cancel, and the filename the server put in `Content-Disposition`. Fetching
 * it into a `Blob`, minting an object URL and revoking it later would be
 * thirty lines to reimplement all of that worse — and it buffers a whole zip
 * in the tab's memory on the way.
 *
 * What it costs: an error is a page the browser navigates to rather than
 * something the console can render. So the routes' refusals are written as
 * prose a person can read (see `export.py`), and the panes disable the link
 * rather than let it be clicked into a 409.
 */
export class HttpExportRepository implements ExportRepository {
  constructor(private readonly baseUrl: string) {}

  courseUrl(projectId: ProjectId, area?: string, format: CourseExportFormat = 'zip') {
    return (
      `${this.baseUrl}/api/projects/${seg(projectId)}/export/course` +
      // `format` omitted when it is the default, so every URL this console
      // built before the HTML export existed is byte-identical to the one it
      // builds now — which is what keeps a bookmark working.
      query({ area: area ?? null, format: format === 'zip' ? null : format })
    )
  }

  graphUrl(
    projectId: ProjectId,
    format: GraphExportFormat,
    scope: GraphExportScope = { kind: 'project' },
  ) {
    return (
      `${this.baseUrl}/api/projects/${seg(projectId)}/export/graph` +
      query({
        format,
        scope: scope.kind,
        area: scope.kind === 'area' ? scope.slug : null,
        entity: scope.kind === 'entity' ? scope.entityId : null,
        depth: scope.kind === 'entity' ? scope.depth : null,
      })
    )
  }
}
