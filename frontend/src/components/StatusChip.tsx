import { statusColorClass } from "../api/types";

/** Small uppercase status word — typography and semantic ink, no pill. */
export function StatusChip({ status, pulse = false }: { status: string; pulse?: boolean }) {
  return (
    <span
      data-status={status}
      className={[
        "font-mono text-[10px] tracking-[1.5px] uppercase",
        statusColorClass(status),
        pulse && status === "PROCESSING" ? "status-pulse" : "",
      ].join(" ")}
    >
      {status.replaceAll("_", " ")}
    </span>
  );
}
