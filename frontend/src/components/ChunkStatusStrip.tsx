import type { ChunkInfo } from "../api/types";
import { StatusChip } from "./StatusChip";

/**
 * One equal-width hairline cell per chunk, in ordinal order. During a live
 * job this is where the fan-out (and the kill-the-worker stall) is visible.
 */
export function ChunkStatusStrip({ chunks }: { chunks: ChunkInfo[] }) {
  return (
    <div
      className="grid divide-x divide-border border border-border"
      style={{ gridTemplateColumns: `repeat(${Math.max(chunks.length, 1)}, minmax(0, 1fr))` }}
      data-testid="chunk-strip"
    >
      {chunks.map((chunk) => (
        <div key={chunk.ordinal} className="flex flex-col gap-1.5 px-3 py-2.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-[14px] text-teal tabular-nums">
              {String(chunk.ordinal + 1).padStart(2, "0")}
            </span>
            <span
              className="truncate font-mono text-[9px] tracking-[1px] text-faint"
              title={chunk.audioPath}
            >
              {chunk.audioPath}
            </span>
          </div>
          <StatusChip status={chunk.status} pulse />
          <AttemptDots attempts={chunk.attempts} />
        </div>
      ))}
    </div>
  );
}

function AttemptDots({ attempts }: { attempts: number }) {
  if (attempts <= 0) {
    return <span className="h-[5px]" aria-hidden />;
  }
  return (
    <span
      className="flex items-center gap-1"
      title={`${attempts} ASR attempt${attempts === 1 ? "" : "s"}`}
    >
      {Array.from({ length: Math.min(attempts, 4) }, (_, i) => (
        <span
          key={i}
          className="h-[5px] w-[5px] rounded-full bg-border-light"
          aria-hidden
        />
      ))}
      <span className="font-mono text-[9px] tracking-widest text-faint tabular-nums">
        ×{attempts}
      </span>
    </span>
  );
}
