# The console reimagining: what is being built, in order

A running order rather than a design. Each numbered item gets its own spec,
its own branch and its own PR, merged when CI is green before the next starts
— because several of them touch the same files and two branches over one
surface is an unplanned merge.

Written down because the ask arrived as one paragraph covering roughly two
weeks of work, and a paragraph is not a thing anyone can resume from.

## 1. Topic actions on the row — IN FLIGHT

Spec: `topic-actions-on-the-row.md`. The queue header's four project-wide
bands become a toolbar; per-topic verbs move onto the rows; the unbounded
autonomous run's console surface is deleted in favour of a bounded fan-out.

## 2. The holding session stops being something a person manages

**The ask, verbatim in substance:** the "holding session" concept is reworked
completely. Its components could live more cleanly. Accept that for the most
part we always just want to see the head state — make holding-session-ness a
*background concern* rather than something the user manages, on the project
list view, the detail views, everywhere.

What this means concretely, to be argued properly in its own spec:

- A project page defaults to the head of the project's own lineage. Which
  session currently holds the project is an implementation fact about where
  the next write goes, not a thing a reader picks.
- The `session` facet stops being a tab a person navigates to in order to see
  the current state, and becomes the thing you open when you specifically want
  the transcript.
- **Project files are readable from the main tabbed project view.** Today the
  workspace tree is reachable only through the holder. It should not be.
- **Chat with an active session is unobtrusive** — present when there is one,
  not a third of the page when there is not.

Watch for: `useProject`'s `holdingSessionId` has consumers that are load-bearing
(the autonomy lock records writes against it). "Background concern" must not
become "silently absent", which is the `silent-defaults-hide-missing-wiring`
failure this repo has already paid for.

## 3. Light and dark modes

Across the board, not the dark-only build there is today. `tokens.css` is
where the vocabulary lives; the traps are already documented in `CLAUDE.md`
(unlayered rules beat utilities; jsdom returns only inline styles, so a theme
assertion has to be a browser measurement).

## 4. The project list view (index page), reimagined for zero friction

Its own spec. "As friction free as possible" is the whole brief.

## 5. The catalog page

Explicitly the one to do last, and the one with the most latitude: *make it
COOL, pretty, and awesome.*

## Standing constraints on all of the above

- **Lean hard on frontend libraries** where they cut effort and improve
  maintainability, rather than hand-rolling. This is a deliberate reversal of
  the console's current default and applies to every item below item 1 —
  headless component primitives, animation, theming, layout. Each adoption is
  a bundle-size decision, and the standing preference is exploration over
  bundle size: raise the budget rather than shave features.
- **Breaking changes are welcome** where they improve quality, maintainability
  or UX. The project is pre-release; break data, events and contracts rather
  than migrating them.
- **The UX should be immaculate.** That is the bar being asked for, and it is
  higher than "no defects".
- Each unit of work: open a PR, merge it when CI goes green, then start the
  next.
