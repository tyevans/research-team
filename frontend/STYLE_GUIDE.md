# The console style guide

This document tells you what the console must look like and how it must feel.
It is the ideal, not a report of the current code. Where a stylesheet disagrees
with this document, the stylesheet is wrong.

`CLAUDE.md` tells you how the CSS behaves and where it breaks. This file tells
you what to build with it.

---

## 1. The identity

The console is an **instrument**, not a document and not a dashboard.

A person opens it to read machine work: event logs, extraction runs, entity
graphs, agent dialogue. The work is dense, it arrives over time, and most of it
is not interesting. The interface has one job — **let a reader find the
interesting part fast and stay in it.**

Three words hold the whole design:

| Word | What it means here |
|---|---|
| **Quiet** | The surface says nothing on its own. Every mark on screen is data or a control. |
| **Dense** | Small type, tight rhythm, many rows visible at once. Scrolling is a cost. |
| **Legible** | Density never costs contrast. Every ink clears WCAG AA on every surface it can land on. |

The reference feel is a **terminal that a typographer designed**: monospace
machinery, warm surfaces, one amber accent, and prose set in a serif so the
human words separate from the machine words at a glance.

Reject these, always:

- Marketing gradients, glass, glow, or a hero.
- Decorative illustration, mascots, or stock imagery.
- Rounded, spacious "app card" styling that halves the rows on screen.
- A second accent colour added for emphasis.

---

## 2. Colour

### 2.1 One palette, one file

Every colour in the product lives in `theme.css`, in the `@theme` block, as a
`light-dark(light, dark)` pair. `tokens.css` renames those into the vocabulary
the stylesheets use. **Write no colour literal anywhere else.** A hex outside
`theme.css` is a defect, even when it looks correct.

Light and dark are both designed. Light is not an inversion of dark.

### 2.2 The roles

**Surfaces.** Five steps, in elevation order.

- `--bg` — the page.
- `--bg-panel`, `--bg-panel-2` — panes and their inner regions.
- `--bg-raise` — the one raised surface: menus, popovers, toasts.
- `--bg-hover` — the pointer response.

Elevation moves *away from the page* in both schemes. In dark, a raised
surface is lighter. In light, hover is darker. Do not invert this
mechanically; the direction of "further from the page" differs by scheme.

**Lines.** `--line` is the default rule. `--line-soft` divides items inside one
group. `--line-strong` marks a boundary a reader must not cross by accident.

**Ink.** Three tiers, and three only.

- `--fg` — the thing being read.
- `--fg-dim` — labels, metadata, secondary values.
- `--fg-faint` — timestamps, counts, anything a reader skips by default.

The tiers must stay visibly separate. If you need a fourth, you need a
different layout instead.

**Accent.** `--accent` is amber and there is exactly one. Use it for the
current selection, the live state, and the primary action. Nothing else. An
accent that appears four times per screen has stopped meaning anything.
`--accent-fg` is the ink drawn *on* the accent. `--accent-dim` is a border, not
a fill.

**Kinds.** Seven event-kind colours (`--k-session`, `--k-message`, `--k-tool`,
`--k-file`, `--k-turn`, `--k-failure`, `--k-compaction`) carry the only other
colour in the interface. They exist so the log reads as its own legend. Two
rules bind them: each clears AA on every surface, and the seven stay
distinguishable from each other. Never reuse a kind colour to mean something
that is not that kind.

**Tints.** `--tint-*` are backgrounds for chips and boxes. They are checked
from the other side: every ink tier and every kind colour must clear AA on
them.

### 2.3 The contrast rule

**4.5:1 minimum, for every ink, on every surface it can reach.** This is not a
target. It is the constraint that chose the palette.

Measure with axe over the stories, not by eye and not by arithmetic on the
declared value. The composited colour is the one a reader sees.

---

## 3. Type

### 3.1 Three families, three jobs

| Family | Job |
|---|---|
| `--font-mono` | The default. Identifiers, values, paths, log rows, controls, counts. |
| `--font-sans` | Interface prose that is not data: headings, help text, empty states. |
| `--font-serif` | Quoted human words: source excerpts, dialogue, passages. |

The serif is load-bearing. It is what lets a reader follow prose down a page
while tool traffic blurs. Use it only for text a person wrote or said. Never
for a label, and never as a heading face.

### 3.2 The scale

`--text-xs` 10.5 · `--text-sm` 12 · `--text-md` 13 · `--text-lg` 15.5 ·
`--text-xl` 19 · `--text-2xl` 23 — a 1.2 minor third off a 13px body.

`--text-md` is the body. Most of the console sits at `--text-sm` and
`--text-md`. `--text-2xl` appears about once per view. If a design needs a size
between two steps, it needs a different hierarchy.

### 3.3 Weight

Three weights: 400, 500, 600. **There is no bold.** The mono stacks synthesise
700 into a smear, so 600 is the top. Build hierarchy from size, ink tier, and
space — not from weight.

### 3.4 Case and measure

Sentence case everywhere, including buttons and headings. Uppercase is for
short eyebrow labels only, and then with letter-spacing. Prose lines cap at
about 72 characters; data rows run the full width they need.

---

## 4. Space and rhythm

Seven steps: `0, 3, 6, 10, 14, 20, 28` px, as `--spacing-0` … `--spacing-6`.

Only these values. The scale is deliberately short and deliberately tight —
`p-3` (10px) is the normal pane padding, not the minimum. Density is a
feature: a reader must see the row above and the row below the one they are
reading.

Vertical rhythm inside a list is the smallest space that keeps rows separable.
Space between groups is at least two steps larger than space inside a group.
Grouping is done with space first, a `--line-soft` rule second, and a panel
last.

`--radius-md` is 5px and is the only radius. Rails, panes, and full-bleed
regions are square.

---

## 5. Layout

### 5.1 The shape

A fixed top bar (`--topbar-h`, 44px), an optional icon rail (`--rail-w`, 34px),
and a split body of panes. Panes scroll; the chrome does not.

Every pane has the same anatomy: a head with a title and its actions, a body
that scrolls, and an optional footer. Use the `lay-pane-*` primitives. Do not
hand-build a pane.

### 5.2 Breakpoints

`--bp-tight` 561px · `--bp-narrow` 821px · `--bp-wide` 1181px.

Below `--bp-narrow`, a split collapses to one pane at a time with explicit
navigation. Nothing is hidden without a way back to it. The console must be
usable on a phone, and it must not pretend to be a phone app.

### 5.3 Depth

Three z levels and no more: `--z-sticky` 10, `--z-overlay` 100, `--z-toast`
200. Every dismissable layer shares the overlay level. If you want a fourth
level, your layer belongs at one of the three.

One elevation exists — `--shadow-1`. Use it only on `--bg-raise`.

---

## 6. Motion

Motion states a fact. It does not delight.

- **Transitions**: 120–160ms, ease-out, on colour and opacity. Do not animate
  layout.
- **Pulse** means "this is still happening". `--animate-stream-pulse` (1.6s)
  for a live row. `--animate-worker-pulse` (1.4s) for one unfinished worker on
  a wall-clock axis. Two pulses that mean the same thing must run in unison;
  two that mean different things must not.
- **Entry**: a toast fades in over 160ms. Nothing else enters with motion.
- **Never**: parallax, scroll-driven reveals, spring physics, staggered lists,
  looping decorative animation.

Every animation must sit behind `@media (prefers-reduced-motion: reduce)` and
stop there.

---

## 7. States

**Focus.** A 2px `--accent` outline at `+1px` offset, on `:focus-visible`. It
is global and it is a decision. When an element must draw its ring inward, use
the `.lay-ring-inward` class — a utility cannot beat the global rule, and no
gate will tell you it failed.

**Hover.** `--bg-hover` on the whole row or control. Hover never moves
anything and never changes type size.

**Selected.** `--accent` on the mark, the border, or the text — one of the
three, not all three. Selection must be readable without colour: pair it with a
weight step, a rule, or a filled marker.

**Disabled.** Reduced opacity plus `cursor: not-allowed`. Never a grey that
drops below AA. A disabled control still has to be readable, because a reader
needs to know what it is before they can find out why it is off.

**Loading.** A skeleton in the shape of the content that is coming, or nothing.
Never a spinner in the middle of a pane.

**Empty.** Say what would be here and give the one action that fills it. An
empty pane is an invitation, not an apology.

**Error.** Say what failed and what to do next, in the interface's voice.
Errors do not apologise and are never vague. Use `--k-failure` and
`--tint-fail`; never make an error the loudest thing on a screen that also
shows working data.

---

## 8. Controls

- The default button is quiet: no fill, a `--line` border, `--fg` text.
- The primary button fills with `--accent` and sets `--accent-fg`. **One per
  view.**
- A destructive button uses `--quiet-line` at rest and `--quiet-line-hover` on
  hover. It must be findable without competing, and firm up when a person
  reaches for it.
- Inputs sit on `--bg-panel-2` with a `--line` border, and are set in
  `--font-mono` when they hold a value the machine also prints.
- Targets are at least 24px tall. Density stops there.

Anything the console styles as a control must actually be that element. Style a
`<button>`; do not make a `<div>` behave like one.

---

## 9. Words

Copy is design material. Write it with the same care as spacing.

- Name things by what a person controls, never by how the system is built.
- Active voice. A control says what happens: "Rebuild the index", not "Submit".
- One name per action, through the whole flow. "Publish" produces "Published".
- Sentence case. No exclamation marks. No filler.
- Specific beats clever, every time.
- Each element does one job. A label labels; an example demonstrates.

---

## 10. Accessibility floor

This floor is not negotiable and is not a feature to be scheduled.

1. Every ink clears 4.5:1 on every surface it can land on.
2. Colour never carries meaning alone. A kind colour is always paired with a
   glyph or a word.
3. Every control is reachable by keyboard, in reading order, with a visible
   focus ring.
4. `prefers-reduced-motion` stops every animation.
5. `axe` runs clean over every story.

---

## 11. How to add something

1. **Use a token.** If the value you want does not exist, argue for the token
   before you write the literal.
2. **Use a primitive.** `lay-pane`, `lay-split`, `lay-layer` exist so panes
   agree with each other.
3. **Spend boldness once.** A view gets one memorable element. Everything
   around it stays quiet.
4. **Remove one thing.** Before you ship a view, take out the least load-
   bearing mark on it. Ship it without.
5. **Measure, do not reason.** Anything whose correctness is a computed style
   or a measurement needs a browser test (`npm run test:browser`). jsdom lays
   nothing out, so a rule that never applied and a rule that worked look
   identical to it.
