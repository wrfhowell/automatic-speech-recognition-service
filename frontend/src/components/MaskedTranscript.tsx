import { useMemo } from "react";
import { maskLegend, parseMaskedTranscript } from "../lib/maskedSpans";

// Fixed inks for the known PHI types; unknown labels fall back to muted.
const MASK_COLORS: Record<string, string> = {
  NAME: "text-purple",
  DATE: "text-gold",
  PHONE: "text-teal",
  MRN: "text-teal",
  LOC: "text-green",
  AGE: "text-gold",
};

function maskColor(label: string): string {
  return MASK_COLORS[label] ?? "text-muted";
}

export function MaskedTranscript({ text, raw = false }: { text: string; raw?: boolean }) {
  const segments = useMemo(() => parseMaskedTranscript(text), [text]);
  const legend = useMemo(() => maskLegend(segments), [segments]);

  return (
    <div>
      {legend.length > 0 ? (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="font-mono text-[9px] tracking-widest uppercase text-faint">
            masked
          </span>
          {legend.map((label) => (
            <span
              key={label}
              className={`rounded-sm bg-tag px-1.5 py-0.5 font-mono text-[10px] tracking-[1px] uppercase ${maskColor(label)}`}
            >
              {label}
            </span>
          ))}
        </div>
      ) : null}
      <div
        className={[
          "max-w-prose whitespace-pre-wrap border-l pl-4 text-[15px] font-light leading-[1.75]",
          raw ? "border-accent" : "border-border",
        ].join(" ")}
        data-testid="transcript"
      >
        {segments.map((segment, i) => {
          if (segment.kind === "text") {
            return <span key={i}>{segment.text}</span>;
          }
          if (segment.kind === "mask") {
            return (
              <span
                key={i}
                data-mask={segment.label}
                className={`mx-px rounded-sm bg-tag px-1 py-px font-mono text-[11px] tracking-[1px] uppercase ${maskColor(segment.label)}`}
              >
                {segment.label}
              </span>
            );
          }
          return (
            <span
              key={i}
              data-gap={segment.chunk}
              className="mx-px rounded-sm border border-accent/40 px-1.5 py-px font-mono text-[11px] tracking-[1px] uppercase text-accent"
            >
              chunk {segment.chunk} unavailable
            </span>
          );
        })}
      </div>
    </div>
  );
}
