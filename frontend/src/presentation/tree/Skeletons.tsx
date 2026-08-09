/** Placeholder rows at the height the real ones will be.
 *
 * Not `loading projects…`. Every log frame invalidates this page's queries, so
 * a text line that appears and vanishes where content is about to land is the
 * thing that makes a live page feel unstable — the layout jumps on a refetch
 * that changed nothing. A block of the right size does not move when it is
 * replaced. `Loading` keeps its job inside panes that are not polled.
 */
export const SkeletonRows = ({ count }: { count: number }) => (
  <ul className="rows rows-skeleton" aria-hidden="true">
    {Array.from({ length: count }, (_, index) => (
      <li key={index} className="skeleton-row" />
    ))}
  </ul>
)
