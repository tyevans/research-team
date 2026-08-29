import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { ApiError } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import type { ResolvedSettings, ScopeRef } from '@domain/settings/layer.ts'
import type { Scope } from '@domain/settings/spec.ts'

import { FORBIDDEN_COPY } from './permissions.ts'

/** What a commit can end as, once. */
export type CommitOutcome =
  | { readonly kind: 'idle' }
  | { readonly kind: 'saved' }
  /** The override was removed and the setting now resolves from below. */
  | { readonly kind: 'cleared' }
  /** `DELETE` answered 404: there was nothing to clear. Its own outcome rather
   *  than an error, because the contract makes that status deliberate —
   *  clearing a key that was never set is almost always a misspelling, and a
   *  silent success is how the misspelling survives. The UI has to be able to
   *  say which of the two happened, so the hook has to be able to. */
  | { readonly kind: 'nothing-to-clear' }
  /** The server refused. `detail` is the server's own sentence — including the
   *  `AGENT_SETTINGS_KEY` one, which is a deployment problem the person cannot
   *  fix from this page and which therefore must not be reworded into a
   *  generic validation message. */
  | { readonly kind: 'refused'; readonly detail: string }

/** The two resolutions a settings page holds, as the keys they are cached
 *  under. Both are invalidated by any write: the fallback resolution is the
 *  *same route with this scope omitted*, and clearing an override changes
 *  which layer answers, not only what this scope holds. Invalidating one and
 *  not the other is how a row comes to claim it falls back to a value that is
 *  now its own. */
const affectedKeys = (chain: readonly ScopeRef[], below: readonly ScopeRef[]) => [
  queryKeys.settings.resolved(chain),
  queryKeys.settings.resolved(below),
]

/** One field's write, with the page's feedback attached.
 *
 * **Per field, because the contract is per key and there is no batch.** A
 * "Save all" button over thirty-nine settings is thirty-nine requests with a
 * partial-failure story nobody can render; this takes the shape the API
 * already offers. The consequence worth stating is the one S3 depends on: one
 * 422 cannot discard a neighbouring good value, because the neighbour was
 * never part of this request.
 *
 * **The optimistic write is what makes the transition legible.** Typing into
 * an inherited row and committing is supposed to turn the bar accent, change
 * the chip and produce a `Clear` — that transition is the page's main feedback
 * that anything happened, and waiting a round trip for it makes a successful
 * save look like a no-op. So the resolved cache is patched before the request
 * and rolled back if it fails. The patch sets `layer` and `scopeId` to this
 * scope, which is exactly what the server will report back.
 *
 * **What is deliberately not rolled back: the caller's draft.** On a refusal
 * this hook restores the *cache* and leaves the field alone, which is S3's
 * central requirement — a form that loses a pasted API key on a failed save is
 * the defect to design out — and it holds for ordinary strings too.
 */
export const useSettingCommit = ({
  scope,
  scopeId,
  chain,
  below,
}: {
  scope: Scope
  scopeId: string
  chain: readonly ScopeRef[]
  below: readonly ScopeRef[]
}) => {
  const { settings } = useContainer()
  const client = useQueryClient()
  const [outcome, setOutcome] = useState<CommitOutcome>({ kind: 'idle' })

  const key = queryKeys.settings.resolved(chain)

  /** Patch one key's resolution in place, and hand back what was there. The
   *  previous *whole* response rather than the one row: React Query rolls back
   *  by writing a value, and re-inserting one row into a list that may have
   *  been refetched underneath would be a merge nobody asked for. */
  const patch = async (
    change: (previous: ResolvedSettings) => ResolvedSettings,
  ): Promise<ResolvedSettings | undefined> => {
    await client.cancelQueries({ queryKey: key })
    const previous = client.getQueryData<ResolvedSettings>(key)
    if (previous) client.setQueryData<ResolvedSettings>(key, change(previous))
    return previous
  }

  const settle = (error: unknown): CommitOutcome => {
    if (error instanceof ApiError && error.status === 403) {
      return { kind: 'refused', detail: FORBIDDEN_COPY }
    }
    if (error instanceof ApiError) return { kind: 'refused', detail: error.message }
    return { kind: 'refused', detail: error instanceof Error ? error.message : String(error) }
  }

  const invalidate = () => {
    for (const affected of affectedKeys(chain, below)) {
      void client.invalidateQueries({ queryKey: affected })
    }
  }

  const save = useMutation({
    mutationFn: ({ key: settingKey, value }: { key: string; value: string }) =>
      settings.put(scope, scopeId, settingKey, value),
    onMutate: async ({ key: settingKey, value }) => {
      setOutcome({ kind: 'idle' })
      return {
        previous: await patch((previous) => ({
          ...previous,
          settings: previous.settings.map((row) =>
            row.key === settingKey
              ? // Only a non-secret's value is written into the cache. A
                // secret's resolved `value` is `null` by contract and its
                // `masked` is the server's to compute -- guessing a
                // `set (…1234)` here would be the console inventing a fact
                // about a credential, and the refetch would correct it a
                // moment later with a visible flicker. The layer and the mask
                // are the parts that change and the mask waits.
                { ...row, layer: scope, scopeId, value: row.secret ? null : value }
              : row,
          ),
        })),
      }
    },
    onError: (error, _variables, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
      setOutcome(settle(error))
    },
    onSuccess: () => {
      setOutcome({ kind: 'saved' })
      invalidate()
    },
  })

  const clear = useMutation({
    mutationFn: ({ key: settingKey }: { key: string }) =>
      settings.clear(scope, scopeId, settingKey),
    // No optimistic patch on a clear, and that is a decision rather than an
    // omission. Removing an override means the value falls to *whatever the
    // next layer holds* -- which this cache does not contain; the second
    // resolution does, under a different key. Guessing at it would print a
    // value the refetch then contradicts, and getting that wrong is the exact
    // confusion the fallback line exists to remove. A clear waits.
    onMutate: () => setOutcome({ kind: 'idle' }),
    onError: (error) => setOutcome(settle(error)),
    onSuccess: (removed) => {
      setOutcome(removed ? { kind: 'cleared' } : { kind: 'nothing-to-clear' })
      invalidate()
    },
  })

  return {
    save: (settingKey: string, value: string) => save.mutate({ key: settingKey, value }),
    clear: (settingKey: string) => clear.mutate({ key: settingKey }),
    busy: save.isPending || clear.isPending,
    outcome,
    resetOutcome: () => setOutcome({ kind: 'idle' }),
  }
}
