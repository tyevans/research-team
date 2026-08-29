import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ResolvedSetting } from '@domain/settings/layer.ts'
import type { SettingSpec } from '@domain/settings/spec.ts'

import { SecretField } from './SecretField.tsx'

/** The three states, side by side, because the argument for them is visual.
 *
 * `SecretField` earns a story on the rule the workbench uses — it renders from
 * props alone and fetches nothing — and it earns one *particularly*, because
 * the decision this component is built around is a decision about what is on
 * screen: **there is no fourth state and there is never a row of bullets.** A
 * reader can check the second claim from `SetAndUntouched` in a second, and
 * cannot check it from any amount of prose.
 *
 * `draft` is the prop that separates two of the three. `null` is the masked
 * display; a string — including `''` — is the replacing state. That is why it
 * is not a boolean and why `''` cannot stand in for "not replacing".
 */
const SPEC: SettingSpec = {
  key: 'api_key',
  envVar: 'AGENT_API_KEY',
  type: 'string',
  label: 'API key',
  description: 'The credential the provider is called with.',
  group: 'Models',
  secret: true,
  // `null` for every secret, always. The schema never carries a credential,
  // including a placeholder one — which is why nothing here can show what
  // clearing this would fall back to without the second resolved request.
  default: null,
  choices: [],
  minimum: null,
  maximum: null,
  requiredWhen: null,
  scopes: ['project', 'user', 'tenant'],
}

const resolvedWith = (masked: ResolvedSetting['masked']): ResolvedSetting => ({
  key: 'api_key',
  value: null,
  layer: masked?.present ? 'project' : 'default',
  scopeId: masked?.present ? 'p1' : null,
  secret: true,
  masked,
})

const meta = {
  title: 'settings/SecretField',
  component: SecretField,
  parameters: { layout: 'padded' },
  args: {
    spec: SPEC,
    onDraftChange: () => {},
    onCommit: () => {},
    onClear: () => {},
    canEdit: true,
    busy: false,
    describedBy: undefined,
    id: 'secret',
  },
} satisfies Meta<typeof SecretField>

export default meta

type Story = StoryObj<typeof meta>

/** Nothing stored. An empty password box asking for a paste, and the server's
 *  own words for the absence — `not set`, not a phrase this console invented. */
export const Unset: Story = {
  args: {
    resolved: resolvedWith({ present: false, lastFour: null, display: 'not set' }),
    draft: '',
  },
}

/** Stored, and untouched. **No input element at all.**
 *
 * This is the state the whole design turns on. A row of bullets here would be
 * a *value*: it would live in an input, it would be submittable, and it would
 * be one careless change away from round-tripping to the server as the literal
 * password. There is nothing here to submit. */
export const SetAndUntouched: Story = {
  args: {
    resolved: resolvedWith({ present: true, lastFour: '1234', display: 'set (…1234)' }),
    draft: null,
  },
}

/** Replacing. An empty box — never seeded from anything — plus a Cancel that
 *  returns to the state above. The person re-pastes, which the contract
 *  requires: there is no route that reads a stored secret back. */
export const Replacing: Story = {
  args: {
    resolved: resolvedWith({ present: true, lastFour: '1234', display: 'set (…1234)' }),
    draft: '',
  },
}

/** Mid-flight. Everything disabled, and the field still holding what was
 *  typed — the state a failed save returns *from*, unchanged. */
export const Saving: Story = {
  args: {
    resolved: resolvedWith({ present: false, lastFour: null, display: 'not set' }),
    draft: 'sk-live-…',
    busy: true,
  },
}

/** A key this caller may not change. The mask, and neither verb.
 *
 * Rendered read-only rather than disabled, for the reason `SettingRow` gives:
 * a disabled control is still in the accessibility tree and reads as "you
 * could change this, later". */
export const CannotEdit: Story = {
  args: {
    resolved: resolvedWith({ present: true, lastFour: '1234', display: 'set (…1234)' }),
    draft: null,
    canEdit: false,
  },
}
