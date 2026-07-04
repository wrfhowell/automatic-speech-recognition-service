import { useMutation } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { submitJob } from "../api/queries";
import { SectionLabel } from "../components/SectionLabel";
import { KNOWN_CHUNKS, POISON_CHUNK } from "../lib/chunks";

function CheckBox({
  checked,
  onChange,
  label,
  children,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  children?: React.ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-3">
      <span className="relative flex h-4 w-4 shrink-0">
        <input
          type="checkbox"
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          aria-label={label}
        />
        <span
          aria-hidden
          className={[
            "flex h-4 w-4 items-center justify-center rounded-sm border transition-colors duration-200",
            checked ? "border-border-light bg-surface-3" : "border-border bg-surface",
          ].join(" ")}
        >
        {checked ? (
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path
              d="M1.5 5.5l2.5 2.5 4.5-6"
              stroke="var(--color-ink)"
              strokeWidth="1.25"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        ) : null}
        </span>
      </span>
      {children}
    </label>
  );
}

export function SubmitJob() {
  const navigate = useNavigate();
  const [selected, setSelected] = useState<ReadonlySet<string>>(
    () => new Set(KNOWN_CHUNKS.slice(0, 3)),
  );
  const [userId, setUserId] = useState("demo-user");
  // One key per form session: retries of the same submission are idempotent,
  // a fresh session is a fresh job.
  const [idempotencyKey, setIdempotencyKey] = useState(() => crypto.randomUUID());

  const submission = useMutation({
    mutationFn: submitJob,
    onSuccess: (jobId) => {
      setIdempotencyKey(crypto.randomUUID());
      navigate(`/jobs/${jobId}`);
    },
  });

  const toggle = (path: string, next: boolean) => {
    setSelected((prev) => {
      const draft = new Set(prev);
      if (next) draft.add(path);
      else draft.delete(path);
      return draft;
    });
  };

  const orderedSelection = useMemo(
    () => KNOWN_CHUNKS.filter((c) => selected.has(c)),
    [selected],
  );
  const canSubmit = orderedSelection.length > 0 && userId.trim().length > 0;

  return (
    <div className="max-w-xl entry-appear">
      <header className="mb-8">
        <div className="font-mono text-[10px] tracking-[3px] uppercase text-faint">
          New submission
        </div>
        <h2 className="mt-1 font-serif text-[2.4rem] leading-[1.05] tracking-tight max-w-[16ch]">
          Submit audio for transcription
        </h2>
        <p className="mt-3 text-[15px] font-light leading-[1.75] text-muted">
          Select the audio chunks to transcribe. The service fans them out to the
          ASR vendor in parallel, stitches the results in order, and de-identifies
          the transcript before it is served.
        </p>
      </header>

      <section className="mb-8">
        <SectionLabel
          right={
            <span className="tabular-nums">
              {orderedSelection.length} / {KNOWN_CHUNKS.length} selected
            </span>
          }
        >
          Audio catalog
        </SectionLabel>
        <ul className="divide-y divide-border border-y border-border">
          {KNOWN_CHUNKS.map((path, i) => (
            <li
              key={path}
              className="grid grid-cols-[80px_1fr] items-center gap-x-4 py-2.5 transition-colors duration-200 hover:bg-surface-2 hover:-mx-2 hover:px-2 hover:rounded"
            >
              <span className="font-mono text-[14px] text-teal tabular-nums">
                {String(i + 1).padStart(2, "0")}
              </span>
              <CheckBox
                checked={selected.has(path)}
                onChange={(next) => toggle(path, next)}
                label={`select ${path}`}
              >
                <span className="flex flex-1 items-center gap-2 text-[15px]">
                  <span className="font-mono text-[13px]">{path}</span>
                  {path === POISON_CHUNK ? (
                    <span className="rounded-sm bg-tag px-1.5 py-0.5 font-mono text-[10px] tracking-[1px] uppercase text-accent">
                      always fails
                    </span>
                  ) : null}
                </span>
              </CheckBox>
            </li>
          ))}
        </ul>
        <div className="mt-4 border-l border-border pl-4">
          <CheckBox
            checked={selected.has(POISON_CHUNK)}
            onChange={(next) => toggle(POISON_CHUNK, next)}
            label="include a chunk that always fails"
          >
            <span className="text-[13px] italic text-muted">
              include a chunk that always fails — demonstrates retry exhaustion and
              partial-completion stitching
            </span>
          </CheckBox>
        </div>
      </section>

      <section className="mb-8">
        <SectionLabel>Requester</SectionLabel>
        <div className="flex items-center gap-4">
          <label
            htmlFor="userId"
            className="font-mono text-[10px] tracking-[2px] uppercase text-faint"
          >
            User ID
          </label>
          <input
            id="userId"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            className="w-56 rounded border border-border bg-surface-2 px-2 py-1.5 font-mono text-[11px] placeholder:text-faint focus:border-border-light focus:outline-none"
            placeholder="demo-user"
          />
        </div>
      </section>

      <footer className="border-t border-border pt-4">
        <div className="flex items-center gap-4">
          <button
            type="button"
            disabled={!canSubmit || submission.isPending}
            onClick={() =>
              submission.mutate({
                audioChunkPaths: orderedSelection,
                userId: userId.trim(),
                idempotencyKey,
              })
            }
            className="rounded border border-border bg-surface-3 px-4 py-2 font-mono text-[10px] tracking-widest uppercase transition-colors duration-200 hover:bg-border hover:text-ink disabled:opacity-40"
          >
            {submission.isPending ? "Submitting…" : "Submit job"}
          </button>
          <span className="font-mono text-[9px] tracking-widest uppercase text-faint">
            idempotency-key {idempotencyKey.slice(0, 8)}
          </span>
        </div>
        {submission.isError ? (
          <p className="mt-3 text-[13px] text-accent">
            Submission failed — {submission.error.message}. The idempotency key is
            unchanged; submitting again will not duplicate the job.
          </p>
        ) : null}
      </footer>
    </div>
  );
}
