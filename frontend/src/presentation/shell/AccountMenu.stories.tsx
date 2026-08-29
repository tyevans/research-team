import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Principal } from '@application/ports/repositories.ts'
import { AccountMenu } from './AccountMenu.tsx'
import { ThemeControl } from './ThemeControl.tsx'

/** Who you are signed in as, in the chrome.
 *
 * **Open the menu and use the Theme item in the toolbar while reading this
 * page.** Two things here are judgements no test can make:
 *
 * - **The trigger sits beside `ThemeControl` without competing with it.** They
 *   are the last two controls in the bar and they are the reader's, not the
 *   page's. The account trigger carries a word where the theme carries a
 *   glyph, so it is wider by design -- the question is whether it reads as
 *   part of the same row or as something bolted on. `Beside` below is the only
 *   arrangement in which that can be checked.
 * - **The initials avatar reads as an identity rather than as a bullet.** At
 *   4×4 it is very nearly a dot. If `NoPicture` is indistinguishable from a
 *   list marker, the fallback is wrong -- and it is the case most accounts
 *   will actually be in, since a locally provisioned Zitadel account has no
 *   picture.
 *
 * No `OverlayHost` here, deliberately: `.storybook/preview.tsx` wraps every
 * story in one. A per-story host is what `npm run deleted` forbids, and the
 * rule is right -- the old convention held in one file out of seven, and the
 * six that forgot rendered every trigger with no content and no error,
 * because a portal with no host renders nothing and raises nothing.
 */
const ADA: Principal = {
  subject: '388383938621546499',
  tenantId: '388383928639102979',
  email: 'ada@research-team.localhost',
  displayName: 'Ada Lovelace',
  avatarUrl: '',
  firstSeenAt: '2026-08-01T09:00:00Z',
  lastSeenAt: '2026-08-29T09:00:00Z',
  mirrored: true,
}

const meta: Meta<typeof AccountMenu> = {
  title: 'shell/AccountMenu',
  component: AccountMenu,
  args: { person: ADA, logoutHref: '/auth/logout' },
  decorators: [
    (Story) => (
      <div className="lay-chrome" style={{ justifyContent: 'flex-end' }}>
        <Story />
      </div>
    ),
  ],
}

export default meta

type Story = StoryObj<typeof AccountMenu>

/** The ordinary case: a name and an email, no picture. */
export const NoPicture: Story = {}

/** With an avatar, which is what a provider federated to Google or GitHub
 *  gives. The image is a data URI rather than a URL so the story renders with
 *  no network -- a broken image here would be indistinguishable from the
 *  `onError` fallback the component installs. */
export const WithPicture: Story = {
  args: {
    person: {
      ...ADA,
      avatarUrl:
        'data:image/svg+xml,' +
        encodeURIComponent(
          '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">' +
            '<rect width="16" height="16" fill="%234f7cff"/></svg>',
        ),
    },
  },
}

/** A thin profile: no display name and no email, which the identity provider
 *  is entitled to give us. The subject is the last resort and is genuinely bad
 *  -- it tells a person nothing about which account they are in -- and it is
 *  here so that badness is visible rather than argued about. If this looks
 *  unacceptable, the fix is upstream in the claim mapping, not in a nicer
 *  fallback string. */
export const NothingButASubject: Story = {
  args: { person: { ...ADA, displayName: '', email: '' } },
}

/** Beside the theme control, which is where it actually lives. The only
 *  arrangement in which the "same row, not bolted on" question above can be
 *  answered. */
export const Beside: Story = {
  render: (args) => (
    <>
      <ThemeControl />
      <AccountMenu {...args} />
    </>
  ),
}

/** A long name, truncated. The trigger caps at 12 characters so the bar's
 *  width does not depend on whose account is open -- a chrome that reflows
 *  when a different person signs in is a layout that shifts for no reason the
 *  reader can see. */
export const LongName: Story = {
  args: { person: { ...ADA, displayName: 'Augusta Ada King-Noel, Countess of Lovelace' } },
}
