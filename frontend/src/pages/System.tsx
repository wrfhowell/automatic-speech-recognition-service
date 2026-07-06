import { useQuery } from "@tanstack/react-query";
import { opsQuery } from "../api/queries";
import { JOB_STATUSES, statusColorClass } from "../api/types";
import { EvidenceCard } from "../components/EvidenceCard";
import { SectionLabel } from "../components/SectionLabel";
import { formatSeconds } from "../lib/format";

const CHUNK_STATUSES = ["PENDING", "PROCESSING", "COMPLETED", "FAILED"] as const;

function StatusLedger({
  statuses,
  counts,
}: {
  statuses: readonly string[];
  counts: { [status: string]: number };
}) {
  return (
    <div className="grid grid-cols-[1fr_80px] max-w-md">
      {statuses.map((status) => (
        <div
          key={status}
          className="contents [&>*]:border-b [&>*]:border-border [&>*]:py-1.5"
        >
          <div
            className={`font-mono text-[11px] tracking-[2px] uppercase ${statusColorClass(status)}`}
          >
            {status.replaceAll("_", " ")}
          </div>
          <div className="text-right font-serif text-[15px] tabular-nums">
            {counts[status] ?? 0}
          </div>
        </div>
      ))}
    </div>
  );
}

export function System() {
  const ops = useQuery(opsQuery());

  if (ops.isPending) {
    return (
      <p className="font-mono text-[11px] tracking-[2px] uppercase text-faint entry-appear">
        reading instruments…
      </p>
    );
  }

  if (ops.isError) {
    return (
      <p className="text-[15px] text-accent entry-appear">
        The operational counters could not be retrieved.
      </p>
    );
  }

  const { semaphore, queue, jobs, chunks, latency } = ops.data;
  const overCap = semaphore.highWaterMark > semaphore.capacity;

  return (
    <div className="entry-appear">
      <header className="mb-8">
        <div className="font-mono text-[10px] tracking-[3px] uppercase text-faint">
          Operational evidence
        </div>
        <h2 className="mt-1 font-serif text-[2.4rem] leading-[1.05] tracking-tight">System</h2>
        <p className="mt-1 max-w-prose text-[14px] tracking-wide text-faint">
          Live counters from Redis and Postgres, polled every second. The
          high-water mark is the concurrency proof of record: it must never
          cross the vendor cap.
        </p>
      </header>

      <section className="mb-8">
        <SectionLabel>ASR budget</SectionLabel>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <EvidenceCard
            label="In flight"
            value={`${semaphore.held} / ${semaphore.capacity}`}
            caption="ASR permits held right now"
          />
          <EvidenceCard
            label="High-water mark"
            value={
              <span className={overCap ? "text-accent" : undefined} data-testid="hwm">
                {`${semaphore.highWaterMark} / ${semaphore.capacity}`}
              </span>
            }
            caption={overCap ? "budget breached" : "peak concurrency — never past the cap"}
          />
          <EvidenceCard
            label="Queue depth"
            value={queue.depth}
            caption="chunk tasks awaiting a worker"
          />
          <EvidenceCard
            label="Chunk retries"
            value={chunks.totalRetries}
            caption="transient failures, retried with backoff"
          />
        </div>
      </section>

      <section className="mb-8">
        <SectionLabel>Job latency</SectionLabel>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <EvidenceCard
            label="p50"
            value={formatSeconds(latency.p50Seconds)}
            caption="median submit → terminal"
          />
          <EvidenceCard
            label="p95"
            value={formatSeconds(latency.p95Seconds)}
            caption="tail submit → terminal"
          />
          <EvidenceCard
            label="Completed"
            value={latency.completedJobs}
            caption="jobs measured"
          />
        </div>
      </section>

      <section className="mb-8 grid gap-10 md:grid-cols-2">
        <div>
          <SectionLabel>Jobs by status</SectionLabel>
          <StatusLedger statuses={JOB_STATUSES} counts={jobs} />
        </div>
        <div>
          <SectionLabel>Chunks by status</SectionLabel>
          <StatusLedger statuses={CHUNK_STATUSES} counts={chunks.byStatus} />
        </div>
      </section>
    </div>
  );
}
