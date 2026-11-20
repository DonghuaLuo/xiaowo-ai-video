const CONTENT_WHITESPACE_RE = /\s+/gu

export function countContentChars(text: unknown) {
  return Array.from(
    String(text ?? "").replace(CONTENT_WHITESPACE_RE, "")
  ).length
}
