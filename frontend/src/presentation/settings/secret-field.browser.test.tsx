import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { expect, it } from 'vitest'

import type { Container } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { SettingsRepository } from '@application/ports/repositories.ts'
import type { ResolvedSetting } from '@domain/settings/layer.ts'
import type { SettingSpec } from '@domain/settings/spec.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { SettingRow } from './SettingRow.tsx'

/** The credential field's *painted* state, which jsdom cannot see.
 *
 * The jsdom suite next door already asserts the three states, the absent
 * input, the opt-outs and the surviving paste — everything decidable from the
 * DOM. What is left here is the class of thing CLAUDE.md records three
 * instances of, and which a settings page is the largest concentration of in
 * this console: a utility written on a form control that loses silently to an
 * unlayered element selector. `tokens.css` gives every bare `input` a
 * background, a colour and `font: inherit`, and `font` is a shorthand — so a
 * size utility goes along with the colour ones, invisibly.
 *
 * Those rules are in `@layer base` today and this fight is supposedly over.
 * These cases are what says it is still over on the screen that has the most
 * `<input>` elements in the application. `styles/control-defaults.browser.test.tsx`
 * is the general measurement; this is the one on the real component.
 */

const SECRET: SettingSpec = {
  key: 'api_key',
  envVar: 'AGENT_API_KEY',
  type: 'string',
  label: 'API key',
  description: '',
  group: 'Models',
  secret: true,
  default: null,
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
      <ContainerProvider container={{ settings } as unknown as Container}>
        <OverlayHost>{element}</OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>,
  )
}

const secretRow = (resolved: ResolvedSetting) => (
  <SettingRow
    spec={SECRET}
    resolved={resolved}
    fallback={undefined}
    scope="project"
    scopeId="p1"
    chain={[{ scope: 'project', scopeId: 'p1' }]}
    below={[]}
  />
)

const unset: ResolvedSetting = {
  key: 'api_key',
  value: null,
  layer: 'default',
  scopeId: null,
  secret: true,
  masked: { present: false, lastFour: null, display: 'not set' },
}

const stored: ResolvedSetting = {
  key: 'api_key',
  value: null,
  layer: 'project',
  scopeId: 'p1',
  secret: true,
  masked: { present: true, lastFour: '1234', display: 'set (…1234)' },
}

/** A token as the browser itself computes it on an element.
 *
 * Not `getPropertyValue('--mono')`, which hands back the declaration verbatim
 * — single quotes and all — where a computed `font-family` comes back
 * normalised to double quotes. Comparing the two directly fails on punctuation
 * and says nothing about the font. A probe puts both sides through the same
 * normalisation without this file naming a family. */
const asComputed = (property: string, value: string): string => {
  const probe = document.createElement('div')
  probe.style.setProperty(property, value)
  document.body.appendChild(probe)
  const computed = getComputedStyle(probe).getPropertyValue(property)
  probe.remove()
  return computed
}

it('gives the password box the page’s own field colours, not the browser’s', () => {
  const { getByLabelText } = draw(secretRow(unset))
  const style = getComputedStyle(getByLabelText('API key'))

  // `.input` is a class in a stylesheet, so it wins on specificity; what this
  // measures is that the layered bare-`input` defaults did not take the
  // background out from under it. Unlayered — as they were until 2026-08-28 —
  // the element selector at (0,0,1) beat everything, and a field rendered
  // light grey on white and could not be read while being typed into.
  expect(style.backgroundColor).not.toBe('rgb(255, 255, 255)')
  expect(style.color).not.toBe('rgb(255, 255, 255)')
  // A monospace face, because a key is a string somebody compares character by
  // character. This is the one `font: inherit` would silently take.
  expect(style.fontFamily).toBe(asComputed('font-family', 'var(--mono)'))
})

it('holds nothing that can be painted as a value in the masked state', () => {
  const { container } = draw(secretRow(stored))

  // The jsdom suite asserts there is no input. This asserts the *visual*
  // consequence a bullet row would have had: whatever is on screen is text in
  // the page's own ink, sitting on the page's own surface, rather than a field
  // that looks filled. A field that looks filled is what invites a password
  // manager, and a manager filling it is the round trip the contract forbids.
  expect(container.querySelectorAll('input')).toHaveLength(0)
  const display = container.querySelector('span.font-mono') as HTMLElement
  expect(display.textContent).toBe('set (…1234)')
  // Transparent, i.e. the row's own surface shows through -- not a field box.
  expect(getComputedStyle(display).backgroundColor).toBe('rgba(0, 0, 0, 0)')
})

it('leaves Save reachable rather than painted over by the field beside it', () => {
  const { getByRole } = draw(secretRow(unset))
  const save = getByRole('button', { name: 'Save' })
  const box = save.getBoundingClientRect()

  // The `CourseCard` hit test again: the field is `flex-1` and grows, and a
  // flex row whose input overruns its sibling would leave a button that is
  // laid out correctly, measures correctly, and cannot be pressed. Geometry
  // says what was laid out; only a hit test says what was painted.
  const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
  expect(save.contains(hit)).toBe(true)
})
