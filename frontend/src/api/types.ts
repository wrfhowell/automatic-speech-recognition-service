import type { components } from "./schema";

export type TranscriptResult = components["schemas"]["TranscriptResult"];
export type ChunkInfo = components["schemas"]["ChunkInfo"];
export type SearchResponse = components["schemas"]["SearchResponse"];

export const JOB_STATUSES = [
  "PENDING",
  "PROCESSING",
  "COMPLETED",
  "COMPLETED_WITH_ERRORS",
  "FAILED",
] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

export type ChunkStatus = "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";

const TERMINAL_JOB_STATUSES: ReadonlySet<string> = new Set([
  "COMPLETED",
  "COMPLETED_WITH_ERRORS",
  "FAILED",
]);

export function isTerminal(jobStatus: string | undefined): boolean {
  return jobStatus !== undefined && TERMINAL_JOB_STATUSES.has(jobStatus);
}

/** Semantic ink for a status word — muted, never neon. */
export function statusColorClass(status: string): string {
  switch (status) {
    case "PENDING":
      return "text-faint";
    case "PROCESSING":
      return "text-teal";
    case "COMPLETED":
      return "text-green";
    case "COMPLETED_WITH_ERRORS":
      return "text-gold";
    case "FAILED":
      return "text-accent";
    default:
      return "text-muted";
  }
}
