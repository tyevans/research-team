import { useMutation, useQueryClient } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import type { DocumentDraft, DocumentEdit, MediaDraft } from '@application/ports/repositories.ts'
import { queryKeys } from '@application/queries/keys.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

/** Writing to the corpus, one mutation per operation.
 *
 * Beside `use-extraction-queue.ts` and shaped like it: `useMutation`,
 * invalidate on success, and no optimistic write. The reason is the same one
 * that file gives -- the server computes `sha256` and `char_count` in the
 * fold, so the row it answers with is not the row a client could have
 * predicted, and writing a guess into the cache would show a digest that is
 * about to change.
 *
 * All four invalidate `queryKeys.documents(projectId)`. `revise` and
 * `restore` also invalidate `queryKeys.document(projectId, sourceId)`,
 * because they can change the *text*, which is what the reader holds -- and a
 * reader left on a stale key shows the old prose under the new title. `drop`
 * and `create` cannot: a drop changes only the record, and a create has no
 * open reader to leave stale.
 *
 * Toasts stay out of these hooks and go at the call sites, matching
 * `use-documents.ts`'s `onExtract` -- the wording depends on what the answer
 * said, and that is a component-layer decision.
 */
export const useCreateDocument = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (draft: DocumentDraft) => documents.create(projectId, draft),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.documents(projectId) })
    },
  })
}

/** The media twin of `useCreateDocument`, and the same shape for the same
 *  reason: the server computes the digest and the byte count as the bytes go
 *  past, so nothing here could have predicted the row it answers with.
 *
 * Invalidates only the listing. A media upload under an existing id revises
 * that source, but `queryKeys.document` holds *text* -- a key a media source
 * never occupies -- so there is no reader to leave stale. */
export const useUploadMedia = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (draft: MediaDraft) => documents.uploadMedia(projectId, draft),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.documents(projectId) })
    },
  })
}

export const useReviseDocument = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, edit }: { sourceId: SourceId; edit: DocumentEdit }) =>
      documents.revise(projectId, sourceId, edit),
    onSuccess: async (_row, { sourceId }) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.documents(projectId) })
      await queryClient.invalidateQueries({
        queryKey: queryKeys.document(projectId, sourceId),
      })
    },
  })
}

export const useDropDocument = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ sourceId, reason }: { sourceId: SourceId; reason: string }) =>
      documents.drop(projectId, sourceId, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.documents(projectId) })
    },
  })
}

export const useRestoreDocument = (projectId: ProjectId) => {
  const { documents } = useContainer()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (sourceId: SourceId) => documents.restore(projectId, sourceId),
    onSuccess: async (_row, sourceId) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.documents(projectId) })
      await queryClient.invalidateQueries({
        queryKey: queryKeys.document(projectId, sourceId),
      })
    },
  })
}
