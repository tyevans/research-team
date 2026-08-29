import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

/** Leaving the page with a credential typed into it and not saved.
 *
 * The case this is for is narrow and specific: somebody pastes an API key,
 * does not press Save, and clicks a link. The paste is gone, there is no
 * feedback that anything was lost, and the next thing they see is a provider
 * that still does not work. It is worth a prompt for exactly the reason a
 * half-written comment is not — the text cannot be retyped from memory.
 *
 * **Only secrets.** An ordinary setting's draft is visible, re-derivable from
 * the value on screen, and re-typable in two seconds. Guarding those too would
 * make the prompt routine, and a routine prompt is one people learn to dismiss
 * without reading — at which point it stops guarding the case it was built for.
 *
 * Two mechanisms, because there are two ways to leave and neither covers the
 * other. `beforeunload` handles a reload, a close and a navigation out of the
 * app, and the browser writes its own wording — we cannot say what is at
 * stake, only that something is. `hashchange` handles every link inside this
 * console, where the browser offers nothing at all: the hash is put back and
 * the caller is handed the destination to confirm in the console's own
 * `Confirm`, which can name the field.
 */

interface UnsavedSecrets {
  readonly mark: (key: string, dirty: boolean) => void
  readonly dirty: readonly string[]
}

const NOTHING_UNSAVED: UnsavedSecrets = { mark: () => {}, dirty: [] }

const UnsavedSecretsContext = createContext<UnsavedSecrets>(NOTHING_UNSAVED)

/** Which secret fields hold text nobody has saved.
 *
 * **`mark` returns the previous array unchanged when nothing moved, and that
 * is the whole performance story.** It is called from an effect in every
 * secret row on every keystroke; React bails out of a re-render when a state
 * setter returns the identical value, so the common case -- a row saying "still
 * dirty" for the fiftieth character -- costs one comparison and no render. An
 * earlier draft kept the set in a `useRef` with a version counter to get the
 * same property, and could not: reading `ref.current` during render is what
 * this repo's `react-hooks` refs rule forbids, which is the same wall the
 * interaction log's per-page identity hit.
 *
 * The silent default above is the shape CLAUDE.md warns about under the
 * interaction log -- a no-op default makes "never wired" and "working"
 * identical -- so the guard's own test drives a real provider and asserts the
 * hash was restored, never that nothing threw. */
export const useUnsavedSecrets = (): UnsavedSecrets => {
  const [dirty, setDirty] = useState<readonly string[]>([])

  const mark = useCallback((key: string, isDirty: boolean) => {
    setDirty((previous) => {
      const had = previous.includes(key)
      if (isDirty === had) return previous
      return isDirty ? [...previous, key] : previous.filter((other) => other !== key)
    })
  }, [])

  return { mark, dirty }
}

export const UnsavedSecretsProvider = UnsavedSecretsContext.Provider

/** Called by a row to report whether its secret draft holds unsaved text.
 *
 * In an effect rather than during render, because `mark` writes to a ref the
 * provider owns and a render-phase write to somebody else's ref is the kind of
 * thing that works until React starts a render it then throws away. */
export const useMarkUnsaved = (key: string, dirty: boolean) => {
  const { mark } = useContext(UnsavedSecretsContext)
  useEffect(() => {
    mark(key, dirty)
    return () => mark(key, false)
  }, [key, dirty, mark])
}

export const useUnsavedCount = (): number => useContext(UnsavedSecretsContext).dirty.length

/** The guard itself, for the page to mount once.
 *
 * `pending` is the hash somebody tried to navigate to while a secret was
 * unsaved; the hash has already been put back, so the page is still where it
 * was and the caller can render a `Confirm` naming what is at stake. `proceed`
 * goes there for real; `stay` forgets it. */
export const useUnsavedGuard = (
  dirtyCount: number,
): { pending: string | null; proceed: () => void; stay: () => void } => {
  const [pending, setPending] = useState<string | null>(null)
  const here = useRef(window.location.hash)
  /** Set while this hook is itself rewriting the hash, so the `hashchange` its
   *  own restore fires is not mistaken for a second attempt to leave —
   *  which would restore again, forever. */
  const restoring = useRef(false)

  useEffect(() => {
    if (dirtyCount === 0) return undefined
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      // `preventDefault` is the specified way; `returnValue` is what older
      // Chromium still reads. Both, because the cost of the dead one is a line.
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirtyCount])

  useEffect(() => {
    const onHashChange = () => {
      if (restoring.current) {
        restoring.current = false
        return
      }
      if (dirtyCount === 0) {
        here.current = window.location.hash
        return
      }
      const target = window.location.hash
      if (target === here.current) return
      setPending(target)
      restoring.current = true
      window.location.hash = here.current
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [dirtyCount])

  return {
    pending,
    proceed: () => {
      const target = pending
      setPending(null)
      if (target === null) return
      // `here` moves first, so the resulting `hashchange` sees a target equal
      // to where we now think we are and lets it through rather than bouncing
      // it back into a second prompt.
      here.current = target
      window.location.hash = target
    },
    stay: () => setPending(null),
  }
}
