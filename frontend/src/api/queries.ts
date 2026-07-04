import {
  infiniteQueryOptions,
  queryOptions,
  type QueryClient,
} from "@tanstack/react-query";
import { client } from "./client";
import type { SearchResponse, TranscriptResult } from "./types";

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
