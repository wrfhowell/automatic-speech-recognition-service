import type { ReactNode } from "react";

/** Tufte evidence stat: mono label, serif number, muted caption. */
export function EvidenceCard({
  label,
  value,
  caption,
}: {
  label: string;
  value: ReactNode;
  caption?: ReactNode;
}) {
  return (
    <div className="border border-border bg-surface/40 p-4">
      <div className="font-mono text-[10px] tracking-[2px] uppercase text-faint">{label}</div>
      <div className="mt-1 font-serif text-[1.8rem] leading-none tabular-nums">{value}</div>
      {caption ? <div className="mt-1.5 text-[12px] text-muted">{caption}</div> : null}
    </div>
  );
}
