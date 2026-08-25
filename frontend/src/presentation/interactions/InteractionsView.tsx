/** The interaction log's reader.
 *
 * A heading and nothing else, on purpose: T5 builds the four regions the spec
 * describes -- health strip, filter bar, summary, feed -- and this slice's
 * work is the route that reaches them. The placeholder is here rather than
 * absent so `#/i` renders a page a person can land on, and so the header link
 * and `viewNameOf` can be tested against something rendered rather than
 * against a route object.
 */
export const InteractionsView = () => <h1>Interaction log</h1>
