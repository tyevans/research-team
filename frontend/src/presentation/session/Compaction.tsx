import type { Message } from '@domain/conversation/message.ts'
import { segmentTranscript } from '@domain/conversation/transcript.ts'

import { Disclosure } from '../common/primitives.tsx'
import { plural } from '../formatting/format.ts'
import { Segments } from './Segments.tsx'

/** Nothing was deleted — the log still holds every message, and so does this
 *  pane. What changed is what the *model* is shown: a summary standing in for
 *  everything above the boundary. That distinction is the visible idea here. */
export const Compaction = ({
  summary,
  hidden,
  through,
  open,
  onToggle,
}: {
  summary: string
  hidden: readonly Message[]
  through: number
  open: ReadonlySet<string>
  onToggle: (key: string) => void
}) => (
  <section className="compaction" aria-label="compacted context">
    <div className="compaction-head">
      <span className="compaction-mark" aria-hidden="true" />
      <span className="compaction-title">
        context compacted — the model sees a summary of the first {plural(through, 'message')}
      </span>
    </div>

    {summary ? (
      <Disclosure
        label="summary shown to the model"
        open={!open.has('compaction:summary:closed')}
        onToggle={() => onToggle('compaction:summary:closed')}
      >
        <div className="compaction-summary">{summary}</div>
      </Disclosure>
    ) : (
      <div className="compaction-note">no summary text was returned with this session.</div>
    )}

    <Disclosure
      label={`${plural(through, 'superseded message')} — still in the log, not sent to the model`}
      open={open.has('compaction:messages')}
      onToggle={() => onToggle('compaction:messages')}
    >
      <div className="compaction-msgs">
        <Segments segments={segmentTranscript(hidden, 0)} open={open} onToggle={onToggle} />
      </div>
    </Disclosure>

    <div className="compaction-boundary">
      <span>context boundary · everything below is sent verbatim</span>
    </div>
  </section>
)
