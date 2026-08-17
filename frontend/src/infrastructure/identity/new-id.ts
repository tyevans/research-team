/** A random id, without requiring a secure context.
 *
 * `crypto.randomUUID` is only exposed on a secure origin -- https, or
 * `localhost`. Serve the console over plain http from anything else (a LAN
 * address, a container's hostname, a tunnel that terminates TLS elsewhere) and
 * the whole property is simply absent, so the call throws `crypto.randomUUID
 * is not a function` and takes the page down before it draws. That is how the
 * ask page was unopenable: `AskView` built its chat id at store construction,
 * inside render, so the throw happened during the first paint rather than on
 * the first question.
 *
 * `crypto.getRandomValues` is *not* secure-context-gated and is on every
 * browser this targets, so the fallback is a v4 UUID assembled from it by
 * hand: same 122 bits of entropy from the same CSPRNG, only the convenience
 * wrapper is missing. The last resort below it is `Math.random`, which is not
 * a CSPRNG -- acceptable only because this id names a server-side conversation
 * scoped to a project and is never a secret or a capability. If that ever
 * stops being true, delete the last branch and let it throw.
 */
export const newId = (): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }

  const bytes = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256)
  }

  // Version 4, variant 10xx -- the two fields that make it a well-formed UUID
  // rather than 32 arbitrary hex digits. Anything reading these bytes as a
  // UUID would reject it otherwise.
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80

  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
