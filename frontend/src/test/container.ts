import type { Container } from '@app/container.ts'

/** A `Container` for a fixture, built from the parts the fixture actually needs.
 *
 * **What this replaces, and why the replacement is not cosmetic.** Nine
 * fixtures wrote their container as a partial literal followed by
 * `as unknown as Container` (`BACKLOG.md` B90 filed six; the count had grown to
 * ten by 2026-08-29, which is the finding -- the cast was being copied into
 * every new fixture). `as unknown as` does not narrow a check, it deletes one:
 * the literal is never compared against `Container` at all, so a misspelled key
 * (`dialogue` for `dialogues` -- `container.ts` records that exact one) is
 * accepted by the compiler and resolves to `undefined` at runtime. The symptom
 * is a `TypeError` inside a render naming a property, or a page stuck loading
 * forever, in a suite whose whole job is measurement.
 *
 * `ContainerParts` keeps the convenience the cast was bought for -- a fixture
 * still supplies only the handful of methods its assertions reach -- while
 * putting the keys and the method signatures back under the compiler. A key
 * that is not on `Container` is now an error at the fixture, in one place,
 * rather than a crash somewhere downstream.
 *
 * **The one remaining cast is here, and it is load-bearing rather than
 * hidden.** A real `Container` is thirty repositories deep and no fixture wants
 * thirty fakes, so the parts a fixture does not name are stood up as proxies
 * that throw on first use. That is the deliberate trade: the compiler no longer
 * proves a fixture is complete, so completeness is enforced at run time
 * instead, by an error that names the missing collaborator
 * (`container.lessons.progress`) rather than by `undefined is not a function`.
 * The value of doing it once rather than nine times is that there is now a
 * single place for that message to live.
 *
 * What a test would fail on: give `buildContainer` a key `Container` does not
 * declare, or a method whose signature disagrees with its port, and
 * `npm run typecheck` fails at the fixture.
 */
export type ContainerParts = {
  [K in keyof Container]?: Container[K] extends (...args: never[]) => unknown
    ? Container[K]
    : Partial<Container[K]>
}

/** A stand-in for a collaborator the fixture did not supply.
 *
 * Throwing on the call rather than returning `undefined` is the point: the
 * error is raised at the seam that was never wired, naming it, while the stack
 * still runs through the component that reached for it. Symbols and `then` are
 * let through as `undefined` because the test framework, React and `Promise`
 * resolution all probe those on values they are handed, and answering with a
 * function there reports a fault in the probe rather than in the fixture.
 */
const absent = (key: string): unknown =>
  new Proxy(
    {},
    {
      get(_target, property) {
        if (typeof property === 'symbol' || property === 'then') return undefined
        return () => {
          throw new Error(
            `buildContainer: this fixture supplied no \`${key}\`, and something called ` +
              `container.${key}.${String(property)}(). Add it to the fixture's parts.`,
          )
        }
      },
    },
  )

/** The same treatment one level down, for a repository the fixture supplied
 *  only part of. Without it, a component reaching a *second* method of a
 *  repository the fixture stubbed one method of gets the old
 *  `undefined is not a function` back. */
const withAbsentRest = (key: string, supplied: object): unknown =>
  new Proxy(supplied, {
    get(target, property, receiver) {
      if (property in target || typeof property === 'symbol' || property === 'then') {
        return Reflect.get(target, property, receiver) as unknown
      }
      return () => {
        throw new Error(
          `buildContainer: this fixture's \`${key}\` does not define ` +
            `${String(property)}, and something called it. Add it to the fixture's parts.`,
        )
      }
    },
  })

/** Keys of `Container` that are not objects, so must be supplied outright or
 *  left to their own default rather than proxied. `now` is the whole list; a
 *  clock is one call and a fixture that omits it wants a real number, not a
 *  throw. */
const PLAIN_DEFAULTS = {
  now: () => 0,
}

export const buildContainer = (parts: ContainerParts = {}): Container => {
  const container: Record<string, unknown> = { ...PLAIN_DEFAULTS }
  for (const [key, value] of Object.entries(parts) as [string, unknown][]) {
    if (value === undefined) continue
    container[key] = typeof value === 'object' && value !== null ? withAbsentRest(key, value) : value
  }
  return new Proxy(container, {
    get(target, property, receiver) {
      if (property in target || typeof property === 'symbol') {
        return Reflect.get(target, property, receiver) as unknown
      }
      return absent(String(property))
    },
    // `'x' in container` has to agree with what `get` will hand back, or a
    // consumer probing for a capability sees a hole the proxy would have
    // filled.
    has: () => true,
  }) as Container
}
