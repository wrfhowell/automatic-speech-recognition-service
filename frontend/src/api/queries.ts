import {
  infiniteQueryOptions,
  queryOptions,
  type QueryClient,
} from "@tanstack/react-query";
import { client } from "./client";
import type { OpsResponse, SearchResponse, TranscriptResult } from "./types";

export class HttpError extends Error {
  constructor(public status: number) {
    super(`request failed with status ${status}`);
  }
}

async function fetchTranscript(jobId: string, view?: "raw"): Promise<TranscriptResult> {
  const { data, response } = await client.GET("/transcript/{job_id}", {
    params: { path: { job_id: jobId }, query: view ? { view } : {} },
  });
  if (!data) throw new HttpError(response.status);
  return data;
}

export function transcriptQuery(jobId: string) {
  return queryOptions({
    queryKey: ["transcript", jobId],
    queryFn: () => fetchTranscript(jobId),
    // Absorb the submit -> first-read race (202 committed, replica/read lag):
    // retry 404s a few times before declaring the job missing.
    retry: (failureCount, error) =>
      error instanceof HttpError && error.status === 404 && failureCount < 3,
  });
}

/** Elevated-access read — server writes an audit row on every fetch. */
export function rawTranscriptQuery(jobId: string) {
  return queryOptions({
    queryKey: ["transcript", jobId, "raw"],
    queryFn: () => fetchTranscript(jobId, "raw"),
    staleTime: Infinity,
  });
}

/** Live operational counters for the System panel; polls while mounted. */
export function opsQuery() {
  return queryOptions({
    queryKey: ["ops"],
    queryFn: async (): Promise<OpsResponse> => {
      const { data, response } = await client.GET("/ops");
      if (!data) throw new HttpError(response.status);
      return data;
    },
    refetchInterval: 1000,
  });
}

/** Burst-submit synthetic jobs; the polled ops counters show the effect. */
export async function runLoadTest(): Promise<{ jobsSubmitted: number }> {
  const { data, response } = await client.POST("/ops/loadtest", {
    body: { jobs: 40, chunks: 8 },
  });
  if (!data) throw new HttpError(response.status);
  return data;
}

export interface SearchFilters {
  jobStatus?: string;
  userId?: string;
}

export function searchQuery(filters: SearchFilters) {
  return infiniteQueryOptions({
    queryKey: ["search", filters.jobStatus ?? null, filters.userId ?? null],
    queryFn: async ({ pageParam }): Promise<SearchResponse> => {
      const { data, response } = await client.GET("/transcript/search", {
        params: {
          query: {
            ...(filters.jobStatus ? { jobStatus: filters.jobStatus } : {}),
            ...(filters.userId ? { userId: filters.userId } : {}),
            ...(pageParam ? { cursor: pageParam } : {}),
          },
        },
      });
      if (!data) throw new HttpError(response.status);
      return data;
    },
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.nextCursor ?? undefined,
  });
}

export async function submitJob(body: {
  audioChunkPaths: string[];
  userId: string;
  idempotencyKey: string;
}): Promise<string> {
  const { data, response } = await client.POST("/transcribe", {
    body: { audioChunkPaths: body.audioChunkPaths, userId: body.userId },
    headers: { "Idempotency-Key": body.idempotencyKey },
  });
  if (!data) throw new HttpError(response.status);
  return data.jobId;
}

export function primeTranscript(queryClient: QueryClient, jobId: string): void {
  void queryClient.prefetchQuery(transcriptQuery(jobId));
}
