"""Burst load test against the running compose stack (`make up` first).

Submits a burst of jobs through the public API, polls them to a terminal
state, and reports job latency percentiles plus the semaphore high-water
mark from GET /ops — the evidence that a naive-parallelism burst (jobs ×
chunks would be 320 concurrent ASR calls) never exceeds the vendor budget.

Prints a markdown report to stdout; exits non-zero if any job fails to
reach a terminal state or the high-water mark crosses the cap.

    make loadtest                       # report to stdout
    make loadtest > design/loadtest-results.md
"""

import argparse
import asyncio
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from redis.asyncio import Redis

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.semaphore import HWM_KEY, LEASES_KEY  # noqa: E402

# Every healthy path (audio-file-8.wav is the poison chunk): transient 1/20
# failures get retried, so all jobs must land COMPLETED.
PATHS = [f"audio-file-{n}.wav" for n in (1, 2, 3, 4, 5, 6, 7, 9)]
TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"}


async def submit(client: httpx.AsyncClient, chunks: int) -> tuple[str, float]:
    resp = await client.post(
        "/transcribe",
        json={"audioChunkPaths": PATHS[:chunks], "userId": "loadtest"},
    )
    resp.raise_for_status()
    return resp.json()["jobId"], time.monotonic()


async def run(args: argparse.Namespace) -> int:
    redis = Redis.from_url(args.redis_url)
    await redis.delete(HWM_KEY, LEASES_KEY)  # measure this burst only
    await redis.aclose()

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:
        health = await client.get("/healthz")
        if health.status_code != 200:
            print(f"stack unhealthy at {args.base_url}: {health.text}", file=sys.stderr)
            return 1

        started = datetime.now(UTC)
        submitted = await asyncio.gather(
            *[submit(client, args.chunks) for _ in range(args.jobs)]
        )
        submit_times = dict(submitted)

        latencies: dict[str, float] = {}
        statuses: dict[str, str] = {}
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline and len(latencies) < len(submit_times):
            pending = [j for j in submit_times if j not in latencies]
            results = await asyncio.gather(
                *[client.get(f"/transcript/{job_id}") for job_id in pending]
            )
            now = time.monotonic()
            for job_id, resp in zip(pending, results):
                status = resp.json()["jobStatus"]
                if status in TERMINAL:
                    latencies[job_id] = now - submit_times[job_id]
                    statuses[job_id] = status
            await asyncio.sleep(1)

        ops = (await client.get("/ops")).json()

    hwm = ops["semaphore"]["highWaterMark"]
    capacity = ops["semaphore"]["capacity"]
    stuck = len(submit_times) - len(latencies)
    by_status: dict[str, int] = {}
    for status in statuses.values():
        by_status[status] = by_status.get(status, 0) + 1

    ordered = sorted(latencies.values())
    p50 = statistics.median(ordered) if ordered else None
    p95 = (
        statistics.quantiles(ordered, n=20, method="inclusive")[18]
        if len(ordered) >= 2
        else None
    )

    def fmt(v: float | None) -> str:
        return f"{v:.1f} s" if v is not None else "—"

    print(f"# Load test — {args.jobs} jobs × {args.chunks} chunks")
    print()
    print(f"Run at {started:%Y-%m-%d %H:%M UTC} against `{args.base_url}` ")
    print(f"({args.jobs * args.chunks} chunks total; naive parallelism would be "
          f"{args.jobs * args.chunks} concurrent ASR calls).")
    print()
    print("| metric | value |")
    print("| --- | --- |")
    print(f"| jobs terminal | {len(latencies)} / {len(submit_times)} |")
    print(f"| job status distribution | {by_status} |")
    print(f"| job latency p50 (submit → terminal) | {fmt(p50)} |")
    print(f"| job latency p95 | {fmt(p95)} |")
    print(f"| job latency max | {fmt(ordered[-1] if ordered else None)} |")
    print(f"| semaphore high-water mark | **{hwm} / {capacity}** |")
    print(f"| total chunk retries | {ops['chunks']['totalRetries']} |")
    print()

    failures = []
    if stuck:
        failures.append(f"{stuck} jobs never reached a terminal state")
    if hwm > capacity:
        failures.append(f"budget breached: high-water mark {hwm} > {capacity}")
    if set(by_status) - {"COMPLETED"}:
        failures.append(f"unexpected terminal statuses: {by_status}")
    if failures:
        print("**FAIL:** " + "; ".join(failures))
        return 1
    print(f"**PASS:** all jobs COMPLETED; peak concurrency {hwm} never exceeded "
          f"the vendor budget of {capacity}.")
    print()
    print(f"Reading the latency: this burst deliberately saturates the budget "
          f"({args.jobs * args.chunks} chunks through {capacity} slots of 5–10 s "
          f"calls), so per-job latency is dominated by queueing for the vendor "
          f"cap. The <20 s happy-path target applies to a job submitted with "
          f"budget headroom.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=40)
    parser.add_argument("--chunks", type=int, default=8, choices=range(1, len(PATHS) + 1))
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--timeout", type=float, default=300)
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
