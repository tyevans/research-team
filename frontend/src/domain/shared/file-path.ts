/** A path in the agent's virtual filesystem.
 *
 * A value object rather than a string because three questions get asked of
 * every path in this console — what is its basename, is it markdown, does it
 * equal that other one — and each was answered inline at a different call site
 * before this existed.
 */
export class FilePath {
  private constructor(readonly value: string) {}

  static of(raw: string): FilePath {
    return new FilePath(raw)
  }

  /** The last segment: what a list row shows when the full path is a title. */
  get basename(): string {
    const segments = this.value.split('/')
    return segments[segments.length - 1] ?? this.value
  }

  get extension(): string {
    const name = this.basename
    const dot = name.lastIndexOf('.')
    return dot <= 0 ? '' : name.slice(dot + 1).toLowerCase()
  }

  /** Whether the file viewer should offer a rendered mode for this path. */
  get isMarkdown(): boolean {
    return MARKDOWN_EXTENSIONS.has(this.extension)
  }

  equals(other: FilePath | null | undefined): boolean {
    return other instanceof FilePath && other.value === this.value
  }

  toString(): string {
    return this.value
  }
}

const MARKDOWN_EXTENSIONS = new Set(['md', 'markdown', 'mdown', 'mkd'])
