import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { expect, it } from 'vitest'

import { ContainerProvider } from '@app/container-context.tsx'
import type { SettingsRepository } from '@application/ports/repositories.ts'
import type { ResolvedSetting } from '@domain/settings/layer.ts'
import type { SettingSpec } from '@domain/settings/spec.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { SettingRow } from './SettingRow.tsx'

import { buildContainer } from '../../test/container.ts'

/** The row's provenance bar, its focus ring and its `Clear` target — all three
 *  of which jsdom cannot judge.
 *
 * jsdom applies no stylesheet and returns only what an inline style said, so
 * over there a bar that paints, a bar that does not, and a bar whose class
 * matches no rule are indistinguishable. That is exactly the class of bug
 * CLAUDE.md records three instances of, and the provenance bar is a `border-*`
 * utility fighting the same cascade.
 */

const SPEC: SettingSpec = {
  key: 'model',
  envVar: 'AGENT_MODEL',
  type: 'string',
  label: 'Chat model',
  description: '',
  group: 'Models',
  secret: false,
  default: 'qwen',
  choices: [],
  minimum: null,
  maximum: null,
  requiredWhen: null,
  scopes: ['project', 'user', 'tenant'],
}

const settings = {
  schema: () => Promise.reject(new Error('unused')),
  resolved: () => Promise.reject(new Error('unused')),
  put: () => Promise.resolve(),
  clear: () => Promise.resolve(true),
} as unknown as SettingsRepository

const draw = (element: ReactElement) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={buildContainer({ settings })}>
        <OverlayHost>{element}</OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>,
  )
}

const row = (resolved: ResolvedSetting) => (
  <SettingRow
    spec={SPEC}
    resolved={resolved}
    fallback={undefined}
    scope="project"
    scopeId="p1"
    chain={[{ scope: 'project', scopeId: 'p1' }]}
    below={[]}
  />
)

const overridden: ResolvedSetting = {
  key: 'model',
  value: 'mine',
  layer: 'project',
  scopeId: 'p1',
  secret: false,
  masked: null,
}

const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** `--accent` is declared as a colour keyword or hex; a computed
 *  `border-left-color` is always `rgb(...)`. Paint a probe to get the browser's
 *  own normalisation of the token, so the comparison is like for like without
 *  this file naming a literal. */
const asPainted = (value: string): string => {
  const probe = document.createElement('div')
  probe.style.color = value
  document.body.appendChild(probe)
  const painted = getComputedStyle(probe).color
  probe.remove()
  return painted
}

it('paints the provenance bar on one edge only, in the layer’s own colour', () => {
  const { getByTestId } = draw(row(overridden))
  const style = getComputedStyle(getByTestId('setting-model'))

  // The colour. An unlayered `.chip-*`-style rule beating the utility is how
  // this class of bug shipped twice, and it is invisible from the class
  // attribute — which is present and correct in both the working and the
  // broken build.
  expect(style.borderLeftColor).toBe(asPainted(token('--accent')))
  expect(style.borderLeftWidth).toBe('2px')
  // A directional width *alone* resolves to solid in this build, which is the
  // half of CLAUDE.md's border entry that was wrong for a while. Measured
  // rather than reasoned, here.
  expect(style.borderLeftStyle).toBe('solid')

  // And the three sides nobody asked for stay at zero. This is what
  // `border-solid` beside the directional width would break — the shorthand
  // gives all four sides a style, and the three with no explicit width fall
  // back to the browser's `medium` (~3px), drawing a box.
  expect(style.borderTopWidth).toBe('0px')
  expect(style.borderRightWidth).toBe('0px')
  expect(style.borderBottomWidth).toBe('0px')
})

it('draws no bar for a value that came from the built-in default', () => {
  const { getByTestId } = draw(
    row({
      key: 'model',
      value: 'qwen',
      layer: 'default',
      scopeId: null,
      secret: false,
      masked: null,
    }),
  )
  // Most rows on a fresh page are defaults. Twenty-five faint vertical lines
  // saying "nothing to see" is noise that makes the three that mean something
  // harder to find, so the default draws nothing at all rather than a
  // transparent bar.
  expect(getComputedStyle(getByTestId('setting-model')).borderLeftWidth).toBe('0px')
})

it('distinguishes an inherited row from an overridden one by more than the word', () => {
  const { getByTestId, unmount } = draw(row(overridden))
  const own = getComputedStyle(getByTestId('setting-model')).borderLeftColor
  unmount()

  const inherited = draw(
    row({
      key: 'model',
      value: 'theirs',
      layer: 'tenant',
      scopeId: 't1',
      secret: false,
      masked: null,
    }),
  )
  const other = getComputedStyle(inherited.getByTestId('setting-model')).borderLeftColor

  // The bar and the chip are redundant on purpose -- colour alone fails for a
  // colourblind reader -- but redundant is not the same as inert. If these two
  // ever compute equal the bar has stopped carrying anything.
  expect(own).not.toBe(other)
})

it('keeps the layer chip’s focus ring inside the row rather than clipped by it', async () => {
  const { getByRole, getByTestId } = draw(row(overridden))
  const chip = getByRole('button', { name: /resolved from project/ })
  chip.focus()

  // `.lay-ring-inward` is a named class in `layout.css` at (0,2,0) against the
  // global unlayered `:focus-visible` at (0,1,0). A
  // `focus-visible:outline-offset-*` utility here would be in the attribute,
  // in the bundle, and inert -- layer order is consulted before specificity,
  // and an unlayered normal declaration beats a layered one. This is the
  // measurement that tells the two apart.
  expect(getComputedStyle(chip).outlineOffset).toBe('-2px')

  const ring = chip.getBoundingClientRect()
  const container = getByTestId('setting-model').getBoundingClientRect()
  expect(ring.left).toBeGreaterThanOrEqual(container.left)
  expect(ring.right).toBeLessThanOrEqual(container.right)
})

it('leaves Clear the topmost thing at its own centre', () => {
  const { getByRole } = draw(row(overridden))
  const clear = getByRole('button', { name: 'Clear' })
  const box = clear.getBoundingClientRect()

  // The `CourseCard` check, applied before the defect rather than after it: a
  // row that grows a stretched hover target painting over its own children is
  // exactly that shape, and geometry says what was laid out where only a hit
  // test says what was painted. `contains` rather than identity because the
  // button may hold a text node the point lands in.
  const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
  expect(clear.contains(hit)).toBe(true)
})
