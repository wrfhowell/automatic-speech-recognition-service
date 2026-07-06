import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { searchQuery } from "../api/queries";
import { JOB_STATUSES } from "../api/types";
import { InfiniteSentinel } from "../components/InfiniteSentinel";
import { SectionLabel } from "../components/SectionLabel";
import { StatusChip } from "../components/StatusChip";
import { formatDateTime } from "../lib/format";
import { shortId } from "../lib/format";

export function Search() {
  const [params, setParams] = useSearchParams();
  const jobStatus = params.get("jobStatus") ?? undefined;
  const userId = params.get("userId") ?? undefined;

  const setParam = (key: string, value: string | undefined) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );
  };

  const search = useInfiniteQuery(searchQuery({ jobStatus, userId }));
  const results = search.data?.pages.flatMap((page) => page.results) ?? [];

  return (
    <div className="entry-appear">
      <header className="mb-8">
        <div className="font-mono text-[10px] tracking-[3px] uppercase text-faint">Archive</div>
        <h2 className="mt-1 font-serif text-[2.4rem] leading-[1.05] tracking-tight">
          Transcription records
        </h2>
      </header>

      <section className="mb-8 flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {JOB_STATUSES.map((status) => {
            const active = jobStatus === status;
            return (
              <button
                key={status}
                type="button"
                onClick={() => setParam("jobStatus", active ? undefined : status)}
                className={[
                  "rounded-sm border px-2 py-0.5 font-mono text-[10px] tracking-[1px] uppercase transition-colors duration-200",
                  active
                    ? "border-border-light bg-surface-2 text-ink"
                    : "border-transparent bg-tag text-faint hover:border-border-light",
                ].join(" ")}
              >
                {status.replaceAll("_", " ")}
              </button>
            );
          })}
        </div>
        <input
          value={userId ?? ""}
          onChange={(e) => setParam("userId", e.target.value.trim() || undefined)}
          placeholder="filter by user id"
          className="w-48 rounded border border-border bg-surface-2 px-2 py-1.5 font-mono text-[11px] placeholder:text-faint focus:border-border-light focus:outline-none"
          aria-label="filter by user id"
        />
      </section>

      <SectionLabel
        right={
          search.isSuccess ? (
            <span className="tabular-nums">{results.length} shown</span>
          ) : undefined
        }
      >
        Record ledger
      </SectionLabel>

      {search.isPending ? (
        <p className="font-mono text-[11px] tracking-[2px] uppercase text-faint">
          retrieving records…
        </p>
      ) : search.isError ? (
        <p className="text-[15px] text-accent">The archive could not be searched.</p>
      ) : results.length === 0 ? (
        <p className="max-w-prose text-[13px] italic text-muted">
          No records match these filters.
        </p>
      ) : (
        <>
          <ul className="divide-y divide-border border-y border-border">
            {results.map((result) => (
              <li key={result.jobId}>
                <Link
                  to={`/jobs/${result.jobId}`}
                  className="group grid grid-cols-[150px_1fr] items-baseline gap-x-4 py-4 transition-colors duration-200 hover:bg-surface-2 hover:-mx-2 hover:px-2 hover:rounded"
                >
                  <span className="text-[14px] tracking-wide text-faint tabular-nums">
                    {formatDateTime(result.completedTime)}
                  </span>
                  <span className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1">
                    <span className="font-mono text-[14px] text-teal transition-colors duration-200 group-hover:text-accent">
                      {shortId(result.jobId)}
                    </span>
                    <span className="text-[14px] text-muted">{result.userId}</span>
                    <StatusChip status={result.jobStatus} />
                    <span className="font-mono text-[10px] tracking-widest text-faint tabular-nums">
                      {result.chunks.length} chunk{result.chunks.length === 1 ? "" : "s"}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <InfiniteSentinel
            onVisible={() => search.fetchNextPage()}
            disabled={!search.hasNextPage || search.isFetchingNextPage}
          />
          <p className="mt-6 text-center font-mono text-[10px] tracking-[2px] uppercase text-faint">
            {search.hasNextPage
              ? search.isFetchingNextPage
                ? "retrieving more…"
                : "scroll for more"
              : "— end of record —"}
          </p>
        </>
      )}
    </div>
  );
}
