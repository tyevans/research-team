/** Identifiers, kept apart from the strings that carry them.
 *
 * Every id in this system is a UUID rendered as a string, which means any of
 * them will type-check anywhere another is expected. Branding costs one cast at
 * the boundary and buys a compiler error for `openSession(projectId)` — a
 * mistake that otherwise surfaces as a 404 at runtime.
 */

declare const brand: unique symbol

type Branded<T, B extends string> = T & { readonly [brand]: B }

export type SessionId = Branded<string, 'SessionId'>
export type ProjectId = Branded<string, 'ProjectId'>
export type RunId = Branded<string, 'RunId'>
export type ApprovalId = Branded<string, 'ApprovalId'>
export type SourceId = Branded<string, 'SourceId'>
export type ComponentId = Branded<string, 'ComponentId'>
export type MessageId = Branded<string, 'MessageId'>
export type TopicId = Branded<string, 'TopicId'>

export const SessionId = (raw: string): SessionId => raw as SessionId
export const ProjectId = (raw: string): ProjectId => raw as ProjectId
export const RunId = (raw: string): RunId => raw as RunId
export const ApprovalId = (raw: string): ApprovalId => raw as ApprovalId
export const SourceId = (raw: string): SourceId => raw as SourceId
export const ComponentId = (raw: string): ComponentId => raw as ComponentId
export const MessageId = (raw: string): MessageId => raw as MessageId
export const TopicId = (raw: string): TopicId => raw as TopicId

/** The leading octet of a UUID, which is what every surface here displays.
 *
 * Long enough to be unique in any list a person will actually read, short
 * enough to sit in a chip beside prose. */
export const shortId = (id: string | null | undefined): string =>
  typeof id === 'string' && id.length > 0 ? id.slice(0, 8) : '????????'
