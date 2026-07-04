import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { HttpError, rawTranscriptQuery, transcriptQuery } from "../api/queries";
import { isTerminal } from "../api/types";
import { ChunkStatusStrip } from "../components/ChunkStatusStrip";
import { EvidenceCard } from "../components/EvidenceCard";
import { MaskedTranscript } from "../components/MaskedTranscript";
import { SectionLabel } from "../components/SectionLabel";
import { StatusChip } from "../components/StatusChip";
import { formatDateTime } from "../lib/format";

export function JobDetail() {
  const { jobId = "" } = useParams();
  const [showRaw, setShowRaw] = useState(false);

  const job = useQuery({
    ...transcriptQuery(jobId),
    // Poll at 1 s while the job is live; stop permanently once terminal.
    refetchInterval: (query) =>
      isTerminal(query.state.data?.jobStatus) ? false : 1000,
  });

  const terminal = isTerminal(job.data?.jobStatus);
  // Elevated access: fetched once when toggled on a terminal job, never polled.
  const rawJob = useQuery({
    ...rawTranscriptQuery(jobId),
    enabled: showRaw && terminal,
  });

  if (job.isPending) {
    return (
      <p className="font-mono text-[11px] tracking-[2px] uppercase text-faint entry-appear">
        retrieving record…
      </p>
    );
  }

  if (job.isError) {
    const notFound = job.error instanceof HttpError && job.error.status === 404;
    return (
      <div className="max-w-xl entry-appear">
        <p className="text-[15px] text-accent">
          {notFound ? "No job exists under this identifier." : "The record could not be retrieved."}
        </p>
        <Link
          to="/"
          className="mt-4 inline-block font-mono text-[10px] tracking-[2px] uppercase text-muted transition-colors duration-200 hover:text-ink"
        >
          ← back to submission
        </Link>
      </div>
    );
  }

  const result = job.data;
  const completedChunks = result.chunks.filter((c) => c.status === "COMPLETED").length;
  const transcriptText = showRaw && terminal ? rawJob.data?.transcriptText : result.transcriptText;

  return (
    <div className="entry-appear">
      <header className="mb-8">
        <div className="flex items-center gap-3 font-mono text-[10px] tracking-[3px] uppercase text-faint">
          <span>Job record</span>
          <span className="text-teal normal-case tracking-normal text-[14px]">{result.jobId}</span>
        </div>
        <div className="mt-1 flex items-baseline gap-4">
          <h2 className="font-serif text-[2.4rem] leading-[1.05] tracking-tight">Transcript</h2>
          <span data-testid="job-status">
            <StatusChip status={result.jobStatus} pulse />
          </span>
        </div>
        <div className="mt-1 text-[14px] tracking-wide text-faint">
          requested by <span className="font-mono text-[13px] text-muted">{result.userId}</span>
        </div>
      </header>

      <section className="mb-8 grid grid-cols-2 gap-4 md:grid-cols-4">
        <EvidenceCard label="Chunks" value={result.chunks.length} caption="submitted for transcription" />
        <EvidenceCard
          label="Completed"
          value={`${completedChunks} / ${result.chunks.length}`}
          caption="transcribed successfully"
        />
        <EvidenceCard
          label="Status"
          value={
            <span className="text-[1.1rem] uppercase">
              {result.jobStatus.replaceAll("_", " ")}
            </span>
          }
          caption={terminal ? "terminal — polling stopped" : "live — polling at 1 s"}
        />
        <EvidenceCard
          label="Completed at"
          value={
            <span className="text-[1.1rem] tabular-nums">
              {formatDateTime(result.completedTime)}
            </span>
          }
          caption="server clock, local time"
        />
      </section>

      <section className="mb-8">
        <SectionLabel>Chunk ledger</SectionLabel>
        <ChunkStatusStrip chunks={result.chunks} />
      </section>

      <section className="mb-8">
        <SectionLabel
          right={
            terminal ? (
              <button
                type="button"
                onClick={() => setShowRaw((v) => !v)}
                className={[
                  "rounded border px-2 py-1 font-mono text-[9px] tracking-widest uppercase transition-colors duration-200",
                  showRaw
                    ? "border-accent text-accent"
                    : "border-border bg-surface-3 text-muted hover:bg-border hover:text-ink",
                ].join(" ")}
              >
                {showRaw ? "raw phi visible" : "show raw"}
              </button>
            ) : undefined
          }
        >
          {showRaw && terminal ? "Transcript — raw" : "Transcript — de-identified"}
        </SectionLabel>

        {showRaw && terminal ? (
          <p className="mb-4 max-w-prose text-[12px] italic leading-relaxed text-muted">
            Elevated access: every raw read is recorded in the audit log.
          </p>
        ) : null}

        {!terminal ? (
          <p className="max-w-prose text-[13px] italic text-muted">
            The transcript is stitched and de-identified once every chunk reaches a
            terminal state.
          </p>
        ) : showRaw && rawJob.isPending ? (
          <p className="font-mono text-[11px] tracking-[2px] uppercase text-faint">
            retrieving raw transcript…
          </p>
        ) : showRaw && rawJob.isError ? (
          <p className="text-[13px] text-accent">The raw transcript could not be retrieved.</p>
        ) : transcriptText ? (
          <MaskedTranscript text={transcriptText} raw={showRaw} />
        ) : (
          <p className="max-w-prose text-[13px] italic text-muted">
            No transcript was produced for this job.
          </p>
        )}
      </section>
    </div>
  );
}
