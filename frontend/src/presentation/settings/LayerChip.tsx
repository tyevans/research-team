import { useState } from 'react'

import { RESOLUTION_ORDER, type Layer, type ResolvedSetting } from '@domain/settings/layer.ts'

import { Popover } from '../common/Popover.tsx'

/** Which layer answered, as a word.
 *
 * **The word, not a colour.** The row also draws a 2px bar in the layer's
 * tone, and the two are redundant on purpose: colour alone fails for a
 * colourblind reader, and this repository has twice paid for believing a
 * colour was carrying a meaning on its own. If the bar is ever wrong the chip
 * still says the truth.
 *
 * The chip is a `<button>` because it opens the chain — a `<span>` is
 * focusable by nothing, which is the defect `Chip`'s own docstring records
 * eleven instances of. It is not a `Chip`: `Chip` renders a `<span>` and has
 * no affordance, and wrapping one in a button would be two elements claiming
 * the same box, which is the `CourseCard` shape.
 */
export const LayerChip = ({
  resolved,
  fallback,
  label,
}: {
  resolved: ResolvedSetting
  /** The same key resolved with this scope omitted — what the value would fall
   *  back to. `undefined` when the second resolution has not arrived or does
   *  not carry the key; the popover then says so rather than guessing. */
  fallback: ResolvedSetting | undefined
  /** The setting's own label, so the popover has an accessible name that says
   *  which setting it is explaining. "Where this value comes from" three times
   *  on one screen names nothing. */
  label: string
}) => {
  const [open, setOpen] = useState(false)

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      label={`Where ${label} comes from`}
      className="shadow-lg rounded-[5px] border border-line bg-bg-raise p-3 text-sm"
      trigger={
        <button
          type="button"
          // `lay-ring-inward` rather than a `focus-visible:outline-offset-*`
          // utility: the global `:focus-visible` in `tokens.css` is unlayered,
          // so it beats any layered utility whatever the specificity, and the
          // utility would be present in the attribute, present in the bundle,
          // and inert. That is the failure this class exists to make
          // impossible to reintroduce.
          className="lay-ring-inward cursor-pointer rounded-[3px] border border-line px-2 py-px font-mono text-xs whitespace-nowrap text-fg-dim hover:text-fg"
          aria-label={`${label}: resolved from ${resolved.layer}. Show the whole chain.`}
        >
          {resolved.layer}
        </button>
      }
    >
      <Chain resolved={resolved} fallback={fallback} />
    </Popover>
  )
}

/** The whole chain, on demand and nowhere else.
 *
 * **Rejected: rendering this inline on every row.** It is accurate and
 * unreadable — five lines times twenty-five rows, with most of them saying
 * "default" three times over. The chain answers a question people ask about
 * one setting at a time.
 *
 * What this can and cannot show, stated because the difference is not
 * obvious: the API reports the layer that *answered* and the value it gave,
 * and it does not report what each layer that did not answer holds. So the
 * layers above the answering one are known to be empty (they did not answer),
 * the answering one carries the value, and the layers below are only knowable
 * through the second resolution — which is exactly one of them, the next one
 * that would answer. Every other row below is marked as not consulted rather
 * than as empty, because this page does not know.
 */
const Chain = ({
  resolved,
  fallback,
}: {
  resolved: ResolvedSetting
  fallback: ResolvedSetting | undefined
}) => {
  const answeredAt = RESOLUTION_ORDER.indexOf(resolved.layer)

  return (
    <table className="w-full border-collapse text-xs">
      <caption className="pb-2 text-left text-xs text-fg-dim">
        Resolution runs top to bottom and stops at the first layer holding a value.
      </caption>
      <tbody>
        {RESOLUTION_ORDER.map((layer, index) => (
          <tr
            key={layer}
            className={index === answeredAt ? 'text-fg' : 'text-fg-faint'}
            data-testid={`chain-${layer}`}
          >
            <th scope="row" className="py-px pr-3 text-left font-mono font-normal">
              {layer}
            </th>
            <td className="py-px font-mono">
              {describe(layer, index, answeredAt, resolved, fallback)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

const describe = (
  layer: Layer,
  index: number,
  answeredAt: number,
  resolved: ResolvedSetting,
  fallback: ResolvedSetting | undefined,
): string => {
  if (index < answeredAt) return '—'
  if (index === answeredAt) {
    if (resolved.secret) return resolved.masked?.display ?? 'set'
    return resolved.value === null ? 'not set' : String(resolved.value)
  }
  // The one layer below the answer this page actually knows about: the second
  // resolution's answer, which is by construction the next layer that would
  // answer if this scope's override went away.
  if (fallback && fallback.layer === layer) {
    if (fallback.secret) return fallback.masked?.display ?? 'set'
    return fallback.value === null ? 'not set' : String(fallback.value)
  }
  return 'not consulted'
}
