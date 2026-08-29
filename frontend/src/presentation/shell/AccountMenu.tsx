import { useState } from 'react'

import type { Principal } from '@application/ports/repositories.ts'
import { Menu, MenuItem } from '@presentation/common/Menu.tsx'

/** Who you are signed in as, and the way out.
 *
 * In the chrome by `AutonomyLock`'s test for what belongs in that bar -- *is
 * this a property of the page you happen to be on?* Identity is not; it is a
 * property of the reader, exactly like the theme, and it sits at the far edge
 * beside it.
 *
 * **A menu rather than a cycling button**, which is the opposite of
 * `ThemeControl`'s choice next door, and the difference is worth stating
 * because the two sit together. A theme has three states and no destructive
 * verb, so cycling costs nothing. Signing out is a one-way door, and a control
 * that performs one on a single click -- next to a control that is *designed*
 * to be clicked repeatedly -- is a mis-click that ends a session. The menu is
 * the confirmation.
 *
 * **The trigger names the person, not "account".** A generic label would make
 * the one thing this control exists to tell you -- which account you are in --
 * available only by operating it. That is the unlabelled-icon defect (S-D2)
 * with a word in front of it.
 */
export const AccountMenu = ({ person, logoutHref }: { person: Principal; logoutHref: string }) => {
  const [open, setOpen] = useState(false)
  const name = displayNameOf(person)

  return (
    <Menu
      open={open}
      onOpenChange={setOpen}
      label={`Account: ${name}`}
      trigger={
        <button type="button" className="btn btn-ghost btn-sm" aria-label={`Signed in as ${name}`}>
          <Avatar person={person} name={name} />
          <span className="max-w-[12ch] truncate">{name}</span>
        </button>
      }
    >
      {/* Not a `MenuItem`: this is the menu's heading, and a `role="menuitem"`
          that does nothing is a stop the arrow keys land on and Enter ignores.
          Radix skips anything it does not recognise, which is the behaviour
          wanted here. */}
      <div className="border-b border-line px-3 py-2">
        <div className="text-sm text-fg">{name}</div>
        {person.email ? <div className="text-xs text-fg-dim">{person.email}</div> : null}
      </div>
      <MenuItem
        onSelect={() => {
          // `location.assign`, not a `navigate()`: signing out is a round trip
          // through the server (it revokes the session, clears the cookie, and
          // usually hands off to the identity provider's own logout). A
          // client-side route change would leave the cookie in place and the
          // person signed in, with a UI insisting otherwise.
          window.location.assign(logoutHref)
        }}
      >
        Sign out
      </MenuItem>
    </Menu>
  )
}

/** The best name the identity provider gave us, or the local part of the
 *  email, or the subject.
 *
 *  The subject is the last resort and is genuinely bad -- it is a snowflake id
 *  and tells a person nothing about which of their accounts they are in --
 *  but it is better than an empty string, which reads as a broken control
 *  rather than as a thin profile. The server already falls back from `name`
 *  through three other claims to the email's local part; this is the case
 *  where every one of those was empty. */
const displayNameOf = (person: Principal): string =>
  person.displayName || person.email.split('@')[0] || person.subject

/** The avatar, or initials when there is no picture.
 *
 *  Initials rather than a generic silhouette: at this size a silhouette is the
 *  same shape for every account, which is worse than useless on the one
 *  control whose job is telling two accounts apart.
 *
 *  `alt=""` on the image and `aria-hidden` on the initials, because the button
 *  already carries "Signed in as <name>" -- announcing the name twice is the
 *  duplication `ThemeControl` avoids the same way. */
const Avatar = ({ person, name }: { person: Principal; name: string }) =>
  person.avatarUrl ? (
    <img
      src={person.avatarUrl}
      alt=""
      className="h-4 w-4 shrink-0 rounded-full object-cover"
      // A broken avatar URL is a broken image icon in the chrome of every
      // page. Hiding the element is the only recovery available from here --
      // the URL is the identity provider's and this console cannot correct it.
      onError={(event) => {
        event.currentTarget.style.display = 'none'
      }}
    />
  ) : (
    <span
      aria-hidden
      className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-bg-panel-2 text-[9px] text-fg-dim"
    >
      {name.slice(0, 1).toUpperCase()}
    </span>
  )
