/** The query policy every resolved widget in an answer shares.
 *
 * One constant rather than four copies of the same three lines, because the
 * thing being set is a property of the *shape* -- a data-bound block inside a
 * markdown answer -- and not of any one widget. A per-widget policy is a
 * policy the fifth widget forgets.
 *
 * **`retry: false` against the app's global `retry: 1` (`main.tsx:27`).** The
 * failures these widgets actually meet are permanent by construction: a
 * definition for an inferred node whose id belongs to no stored entity is a
 * 404 forever, a source id the model invented is a 404 forever, and an
 * unparseable `from:` is a 422 forever. Retrying doubles the request and
 * doubles the wait before the reader gets the prose that says so. The cost is
 * real and is accepted: a genuine network blip now shows its sentence instead
 * of quietly recovering, and a reader's remedy is to reload the answer.
 *
 * **`staleTime` of five minutes, and no refetch on mount or focus.** Measured,
 * not reasoned: `GET /timeline` is two full passes over the tenant's entire
 * entity set (`timeline_reader.py:108-115`) and is deliberately uncached, and
 * `limit` is not passed down to the store (`graph_reader.py:294-299`) so it
 * does not govern that cost. The risk this guards is not one expensive query
 * but a page of widgets issuing many cheap-looking ones -- a transcript
 * scrolled back over would re-run that double pass per remount otherwise. The
 * cost: an answer left open across an extraction run shows the corpus as it
 * was when the block first rendered.
 */
export const resolvedWidgetQuery = {
  retry: false,
  staleTime: 5 * 60_000,
  refetchOnMount: false,
  refetchOnWindowFocus: false,
} as const
