# Load test — 40 jobs × 8 chunks

Run at 2026-07-06 20:28 UTC against `http://localhost:8000` 
(320 chunks total; naive parallelism would be 320 concurrent ASR calls).

| metric | value |
| --- | --- |
| jobs terminal | 40 / 40 |
| job status distribution | {'COMPLETED': 40} |
| job latency p50 (submit → terminal) | 32.4 s |
| job latency p95 | 36.1 s |
| job latency max | 43.1 s |
| semaphore high-water mark | **90 / 90** |
| total chunk retries | 42 |

**PASS:** all jobs COMPLETED; peak concurrency 90 never exceeded the vendor budget of 90.

Reading the latency: this burst deliberately saturates the budget (320 chunks through 90 slots of 5–10 s calls), so per-job latency is dominated by queueing for the vendor cap. The <20 s happy-path target applies to a job submitted with budget headroom.
