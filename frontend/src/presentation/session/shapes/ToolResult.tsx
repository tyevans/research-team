import type { ReactNode } from 'react'

import { artifactOf } from '@domain/conversation/artifact.ts'
import { contentText, truncate, type Message } from '@domain/conversation/message.ts'

import { Acknowledgement } from './Acknowledgement.tsx'
import { Delegation } from './Delegation.tsx'
import { EntityList } from './EntityList.tsx'
import { Excerpt } from './Excerpt.tsx'
import { FileChange } from './FileChange.tsx'
import { HitList } from './HitList.tsx'
import { Inventory } from './Inventory.tsx'
import type { Phase } from './parts.tsx'

export const RESULT_TEXT_LIMIT = 4000

/** One tool result, drawn from its artifact — or, failing that, from its text.
 *
 * Neither `ActivityFeed` nor `Segments` knows a shape. That is the whole job of
 * this file: seventeen tools reach seven renderings through one call, and a
 * tool nobody has converted reaches the eighth.
 *
 * **The fallback is a first-class path, not error handling.** Every message in
 * a real database predates artifacts, so on live history it is the common case,
 * and a `null` from `artifactOf` covers three situations that are one situation
 * to the reader: no artifact, a shape this build does not know, and an artifact
 * that failed to parse. All three render what the model itself read.
 *
 * `fallback` exists so each caller keeps its own current markup byte for byte.
 * `ActivityFeed` renders a `provisional-body` and `Segments` a `msg-body mono`;
 * having the dispatcher pick one would silently restyle the other, and "the
 * text is unchanged" is the property the fallback has to be able to claim. */
export const ToolResult = ({
  message,
  phase,
  fallback,
}: {
  message: Message
  phase: Phase
  fallback?: ReactNode
}) => {
  const artifact = artifactOf(message)

  if (!artifact) {
    if (fallback !== undefined) return <>{fallback}</>
    return (
      <div className="stream-fallback">
        {truncate(contentText(message.content), RESULT_TEXT_LIMIT)}
      </div>
    )
  }

  // The header names the tool that actually ran, not the tool the shape was
  // designed around. A shape is shared: `hit_list` serves `search_sources` and
  // `web_search` both, so a name baked into the component is wrong for every
  // producer but one — and wrong while reading as authoritative, which is the
  // worst of both.
  const tool = message.name

  switch (artifact.shape) {
    case 'hit_list':
      return <HitList artifact={artifact} phase={phase} tool={tool} />
    case 'entity_list':
      return <EntityList artifact={artifact} phase={phase} tool={tool} />
    case 'excerpt':
      return <Excerpt artifact={artifact} phase={phase} tool={tool} />
    case 'inventory':
      return <Inventory artifact={artifact} phase={phase} tool={tool} />
    case 'acknowledgement':
      return <Acknowledgement artifact={artifact} phase={phase} />
    case 'file_change':
      return <FileChange artifact={artifact} phase={phase} tool={tool} />
    case 'delegation':
      return <Delegation artifact={artifact} phase={phase} tool={tool} />
  }
}
