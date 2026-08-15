# Below the narrow breakpoint

2026-08-14, branch `narrow-band` off `origin/main` 801a5ae. Closes `BACKLOG.md`
B57's remaining half and B60.

## The headline: the candidate defect was wrong, and a better one was underneath

The slice was briefed around a suspicion: `layout.css` caps `.lay-pane-body` at
`60vh` **unqualified**, where the `page`-mode rule fifty lines above deliberately
writes `:not([data-scroll='regions'])`. HOLDER and MATERIAL are both
`scroll="regions"`, whose body is `overflow: hidden`, and a cap on a box that
cannot scroll clips with no way to reach what it cut.

**Refuted, by measurement.** Every region inside a `regions` body is
`flex: 1 1 0%; min-height: 0` with a scroller of its own, so a capped body hands
the shortfall down and each region scrolls what it cannot show. Adding the
`:not()` would have been a change justified by nothing. QUEUE (`scroll='body'`,
`overflow: auto`) is the pane the cap actually binds on, and it is the one that
can take it.

**What was actually broken: below 821 the surface never scrolled.**
`scrollHeight` and `clientHeight` were both **856 at every width from 820 down to
375** — flat. The split stayed `flex: 1 1 auto`, pinned to the surface, so every
pane shrank below its content to make the set fit one screen:

| | pane | body | content |
| --- | --- | --- | --- |
| QUEUE | 439.0 | 400.5 | 590 |
| HOLDER | 304.6 | 266.1 | 266 |
| **MATERIAL** | **112.3** | 73.8 | 74 |

The `overflow: auto` on the surface had nothing to scroll and never had. This is
the same defect `layout.css` already records and fixes for `page` mode — *"the
innermost scroller absorbs the content and the surface never has anything to
scroll"* — and **the below-narrow half of `auto` was given the overflow and not
the release**, under a comment describing behaviour it did not have. One
declaration: `flex: 0 0 auto`. After: surface 1128/856, panes 578.5 / 401.4 /
148.0.

**A 60vh cap the layout never lets a body reach is not a cap.** That is why the
two findings are one: the brief's suspicion was about the cap, and the cap was
inert because of the defect nobody had looked for.

## It took a better fixture to see it

The two sibling browser files wrap the view in a bare 900px flex column, which
**reproduces the pinned height by accident** and leaves no `.lay-surface` to ask.
The new files mount a real `Shell` and use `height: 100vh` — a fixed pixel height
detaches the shell from the viewport that `60vh` is measured against, and a
700×500 probe reported a 300px cap inside an 856px shell that had not moved.

The same trap has a second form: **the empty session view is shorter than the
screen at every width**, so it measured 856/856 — flat, for the boring reason —
both before and after the fix. That claim only means something with 40 messages
in the transcript.

## The resize helper wants to be one thing, and is three

The plan warned that `widen()` is a silent no-op crossing *down* past 1181,
because it polls on the inline template being empty and that is already true at
1000px. **My proposed fix had the same bug.** I told task B to poll
`data-collapse-to === 'rail'` instead — and `'rail'` is what the attribute says on
*both* sides of 1181, so a 1440 → 821 resize satisfied it on the first tick and
the probe read the 1440 layout: a three-track template and an 880px pane inside
an 821px viewport.

Three browser files now have three different resize helpers, each with its own
version of this bug, each fixed independently. Filed, because that is a shared
primitive asking to exist and the third occurrence is the evidence.

## What shipped

| | before | after |
| --- | --- | --- |
| surface below 821 | never scrolled, panes crushed | scrolls, panes at content height |
| both session flanks folded | one keeps a 966px "rail" | both rail at 34px |
| strip collapse form | never rendered in a browser | 6 claims |
| `.view-head` family | dead rules in two stylesheets | deleted |
| session `workspace` floor | 300 vs a declared 320, unexplained | measured, kept, explained |

**B60 ported**, red-proved at **966px where a rail is 34** — the same arithmetic
(1000 − 34) the project view produced, not a coincidence. The two
`responsive.css` blocks now differ only in their floors.

**The session's 300 stays 300, and that is a result rather than a shrug.**
`workspace` carries the 1.4 weight, so its narrowest share in the entire band is
821 × (1.4/2.4) = **478.9** — the floor cannot bind at any width, and raising it
to match the declared 320 would change no pixel anywhere. Kept, with the same
argument the project block already makes for HOLDER's unreachable 320. What the
arithmetic does *not* prove is that 342 is wide enough, so that half was measured
separately: nothing clips at 821 in any of the three collapse states.

**The `.view-head` deletion found a live defect on its way out.**
`.view-head .sub` was the *only* definition of `.sub` under `src/styles/`, and
`AutonomyAllowAll` needed an ancestor the decision bar never provided — so a
paragraph asking to be dim had been rendering at full `--fg` all along. The
tombstone comment records it. `.view-head` was deliberately **not** added to
`check-deleted.mjs`: the name is generic enough that a future view head could
legitimately want it, and forbidding it would cost more than the reintroduction
it prevents.

## Where it actually breaks, and what was left alone

Swept 820 → 320 and bisected. **Nothing clips from 820 down to 351.** Then:

| what | needs | clips from |
| --- | --- | --- |
| MATERIAL's five-tab strip (`.tabs`, no `flex-wrap`) | 351px | **350px** |
| QUEUE's seeding form | 317px + 27px chrome | **343px** |

**Both recorded, neither fixed**, per the scoping call made before any code was
written: this console has one user on one machine, the band worth effort is
~561–820, and a slice that spends itself making a research console work at 320px
has optimised the wrong thing. The tab-strip fix is also less contained than it
looks — `.tabs` is the class on both `Choices` and `TabList`, so `flex-wrap`
there changes every tab row in the console. One declaration if anyone wants it.

## Verification

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | passed |
| `uv run ruff format --check .` | 230 files already formatted |
| `uv run pytest` | **2391 passed**, 9 deselected, 218s |
| `cd frontend && npm run verify` | full chain — build, size, `deleted`, `check:tailwind` |
| `npm run test:browser` | **24 files / 80 tests** (from 22/70) |

The browser suite was run on the **combined** tree by me, not only by each task
against its own. `app` is **72.6 kB of 80** — *down* 0.1 from the branch point,
because the dead CSS paid for the new rule.

Every claim was proved red or says in its docstring that it would not fail. Two
red proofs were more interesting than their tests: task B's first prediction of
what would break the floor claim was wrong (`minmax(400px)` still passes;
`minmax(600px)` is what squeezes the other column), and task A wrote a boundary
claim expecting it to pass either way and it went red.

`layout.css` was mutated twice for red proofs by a task that does not own it, and
restored byte-identically both times, **verified by md5**.

## Left undone, deliberately

- **The research view below 821.** A's `flex: 0 0 auto` is on the shared
  `.lay-split` primitive, so it reaches that view too. The project and session
  views are now measured there; the research view is **unmeasured rather than
  measured and fine.** Filed.
- **No sweep below 700 on the session view.** It has no equivalent of QUEUE's
  seeding form, but that is a reason to expect it is fine, not a measurement.
- **The 350px and 343px clip points**, recorded above.
- **One shared resize helper.** Three files, three helpers, three versions of the
  same bug. Filed rather than built — it wants a slice that can change all three
  and prove the shared one right.
- **`workspace`'s 300 raised to 320.** Changes no pixel today; whoever merges the
  two `responsive.css` blocks into a primitive should do it then, when the floors
  have to be reconciled anyway.
