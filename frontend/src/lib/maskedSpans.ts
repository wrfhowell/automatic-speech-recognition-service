/**
 * Parses inline de-identification tokens out of a masked transcript.
 *
 * The API ships no span coordinates — masks are inline tokens like `[NAME]`
 * and stitch gaps are `[chunk 3 unavailable]` (1-based). This is pure string
 * logic so it can be unit-tested without React.
 */

export type TranscriptSegment =
  | { kind: "text"; text: string }
  | { kind: "mask"; label: string }
  | { kind: "gap"; chunk: number };

const TOKEN_RE = /\[(?:([A-Z][A-Z_]{1,20})|chunk (\d+) unavailable)\]/g;

export function parseMaskedTranscript(masked: string): TranscriptSegment[] {
  const segments: TranscriptSegment[] = [];
  let cursor = 0;
  for (const match of masked.matchAll(TOKEN_RE)) {
    if (match.index > cursor) {
      segments.push({ kind: "text", text: masked.slice(cursor, match.index) });
    }
    if (match[1] !== undefined) {
      segments.push({ kind: "mask", label: match[1] });
    } else {
      segments.push({ kind: "gap", chunk: Number(match[2]) });
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < masked.length) {
    segments.push({ kind: "text", text: masked.slice(cursor) });
  }
  return segments;
}

/** Unique mask labels in first-appearance order, for the legend. */
export function maskLegend(segments: TranscriptSegment[]): string[] {
  const seen = new Set<string>();
  for (const s of segments) {
    if (s.kind === "mask") seen.add(s.label);
  }
  return [...seen];
}
