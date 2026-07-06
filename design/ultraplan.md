This plan builds the full system described in DESIGN.md: a FastAPI backend with arq workers coordinated by a global Redis semaphore (the 100-slot ASR vendor cap is the defining constraint), Postgres as source of truth with crash recovery, a CIPHER de-identification stage (full model code + tiny demo training), and a Tufte-styled React demo console — all wired via docker-compose against a user-provided Fastify mock ASR server (/mock-asr, untouched).

User decisions: full scope; mock ASR provided by user (build against its contract, confirm exact shape before coding the client); full CIPHER implementation with demo-scale training (bert-tiny, synthetic data, committed weights).

Monorepo layout
/backend
pyproject.toml, Dockerfile, alembic.ini, alembic/versions/0001_initial.py
app/
main.py, config.py # app factory + pydantic-settings
api/ deps.py, schemas.py, transcribe.py, transcript.py, health.py
models/ base.py, job.py, chunk.py, audit.py, enums.py
core/ db.py, semaphore.py, asr_client.py, retry.py, breaker.py, logging.py
workers/ main.py, process_chunk.py, stitch_job.py, reconciler.py, queueing.py
deid/ labels.py, crf.py, viterbi.py, losses.py, model.py, teacher.py,
inference.py, masking.py, train.py, eval.py,
data/{templates.py, generate.py, features.py},
artifacts/{student.pt, config.json, labels.json, metrics.json, data/\*.jsonl}
tests/ unit/ integration/ e2e/ deid/
/frontend
Dockerfile, nginx.conf, vite.config.ts, playwright.config.ts, e2e/smoke.spec.ts
src/ api/{schema.d.ts (generated, committed), client.ts, types.ts, queries.ts}
lib/{chunks.ts, maskedSpans.ts, format.ts}
components/{AppShell, SectionLabel, StatusChip, EvidenceCard,
ChunkStatusStrip, MaskedTranscript, InfiniteSentinel}.tsx
pages/{SubmitJob, JobDetail, Search}.tsx router.tsx styles/index.css
/mock-asr # PROVIDED by user — untouched
docker-compose.yml, .env.example, Makefile
Backend deps: fastapi, uvicorn, pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, arq, redis, httpx, torch (CPU), transformers, faker, numpy. Dev: pytest, pytest-asyncio, respx, fakeredis[lua], testcontainers, ruff.
Frontend deps: react, react-router-dom, @tanstack/react-query, openapi-fetch, tailwindcss + @tailwindcss/vite (v4). Dev: openapi-typescript, @playwright/test, vitest.

Cross-workstream contracts (decided now)
Deid interface: app/deid exports deidentify(text: str) -> DeidResult(masked*text: str, spans: list[PhiSpan]) behind a lazy per-process singleton. stitch_job calls it via asyncio.to_thread(...) and stores result.masked_text as transcript_deid. On deid failure the job stays non-terminal and stitch raises so arq retries — never silently serve raw PHI.
API response shape: keep chunkStatuses: {[audioPath]: status} exactly per DESIGN.md §3 and add chunks: [{ordinal, audioPath, status, attempts}] (ordered array). Frontend uses chunks (ordering + attempt counts for the retry-dots UI); chunkStatuses stays contract-faithful.
Raw transcript access: GET /transcript/{jobId}?view=raw returns transcript_text instead of transcript_deid and inserts a row into an audit_log table (job_id, action='RAW_READ', created_at). Frontend fetches it only when the "show raw" toggle is on and the job is terminal (enabled: showRaw && isTerminal), never polled.
Mask highlighting: frontend parses inline tokens from the masked text with /\[(?:([A-Z]A-Z*]{1,20})|chunk (\d+) unavailable)\]/g — no span coordinates in the API.
Chunk list for Submit screen: hardcoded constant src/lib/chunks.ts (KNOWN_CHUNKS, POISON_CHUNK = "audio-file-8.wav") — the vendor's audio catalog is demo fixture data, not a real API surface. Duplicate selection prevented in UI.
ASR vendor contract: confirmed from the provided /mock-asr source before coding; quarantined in core/asr_client.py (the only vendor-aware module). Also confirm whether the mock exposes a max-in-flight counter; fallback concurrency proof is the semaphore's own Redis high-water-mark key.
Data model (0001_initial Alembic migration)
jobs(id uuid PK default gen_random_uuid(), user_id text, status text CHECK(...),
pending_chunks int NOT NULL, -- stitch-trigger counter, seeded to N
transcript_text text, transcript_deid text,
idempotency_key text UNIQUE, -- PG default = NULLS DISTINCT
created_at timestamptz default now(), completed_time timestamptz)
chunks(id uuid PK, job_id FK ON DELETE CASCADE, ordinal int, audio_path text,
status text CHECK(...), attempts int default 0, transcript_text text,
last_error text, created_at, updated_at, UNIQUE(job_id, ordinal))
audit_log(id PK, job_id FK, action text, created_at)
-- indexes: chunks(job_id); partial chunks(status, updated_at) WHERE status IN ('PENDING','PROCESSING');
-- jobs(user_id, status, created_at DESC, id DESC); jobs(status, created_at DESC, id DESC); jobs(created_at DESC, id DESC)
Statuses are text + CHECK (not PG enums). updated_at touched on every chunk transition — doubles as the reconciler heartbeat. Migration applied by a one-shot migrate compose service; api/worker depends_on: service_completed_successfully.

Backend — critical mechanisms
Global ASR semaphore (core/semaphore.py)
Redis sorted-set of leases, all atomicity in one Lua script: purge expired members (ZREMRANGEBYSCORE to Redis server time), reject if ZCARD >= capacity (90), else ZADD lease_id with score = now + TTL (30 s > 15 s httpx timeout), and maintain a high-water-mark key (asr:sem:hwm) — the concurrency-proof metric. acquire() -> lease_id | None (non-blocking), release(lease_id) (ZREM; 0 rows = expired lease, log warning). Crashed workers' permits self-expire; no janitor. Scaling knob is ASR_MAX_CONCURRENCY=90 — the one config value per §7.

process_chunk task (short transactions; never hold DB tx or queue slot across the ASR call)
Idempotency gate: read chunk; terminal → return (makes redelivery safe).
Breaker open → re-enqueue with defer; return.
semaphore.acquire(); None → re-enqueue with defer=uniform(0.5, 2.0); return.
Guarded UPDATE ... SET status='PROCESSING' WHERE id=:id AND status='PENDING'.
Call ASR inside try/finally: semaphore.release(lease).
Classify (pure mapping in core/retry.py, per §5.2): 200 → finish_chunk(COMPLETED); 404 → finish_chunk(FAILED); 500/timeout → increment attempts, back to PENDING, re-enqueue with full-jitter backoff uniform(0, min(8.0, 0.5·2^(n-1))) (attempt 1 retries ≤0.5 s — the <20 s budget needs a fast first retry); attempts ≥ 4 → finish_chunk(FAILED); 429 → trip breaker, ERROR log ("limiter invariant violated"), long defer, no attempt consumed.
Retries are explicit re-enqueues with defer_by (attempts live in Postgres), arq job_id = f"chunk:{chunk_id}" with keep_result=0 so reconciler/retry duplicates dedupe naturally.

Race-free "last chunk done" → stitch (the core correctness pattern)
One helper, one transaction: guarded terminal UPDATE chunks ... WHERE status NOT IN ('COMPLETED','FAILED') RETURNING job_id — if no row transitioned (redelivery), do nothing; else UPDATE jobs SET pending_chunks = pending_chunks - 1 ... RETURNING pending_chunks. The job row-lock serializes decrements, so exactly one caller sees 0 and enqueues stitch:{job_id} after commit. Crash in the commit→enqueue gap is covered by reconciler query C.

stitch_job
Idempotent: return if job terminal; defensive return if any chunk non-terminal. Concat ORDER BY ordinal with [chunk N unavailable] (1-based, pinned by a test) for failed chunks. Job status: all COMPLETED → COMPLETED; all FAILED → FAILED; mixed → COMPLETED_WITH_ERRORS. Run deid (contract #1), then guarded terminal write (WHERE status NOT IN (terminal)) setting transcript_text, transcript_deid, completed_time.

Reconciler (arq cron, 60 s; queries use FOR UPDATE SKIP LOCKED)
A: stale PENDING (lost enqueue) → touch + re-enqueue.
B: stale PROCESSING > CHUNK_STUCK_SECONDS=120 (> lease TTL + max call, so never races a live call) → reset to PENDING + re-enqueue.
C: jobs non-terminal with pending_chunks=0 → enqueue stitch.
This is the recovery mechanism of record for kill -9 (permit TTL reclaims budget; reconciler re-enqueues; idempotency gate makes redelivery safe).

API specifics
POST /transcribe: validate non-empty paths (cap 64); Idempotency-Key via INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id, on conflict re-select and return that jobId (race-safe). Insert job (pending_chunks=N) + chunks in one tx, commit, then enqueue, return 202.
GET /transcript/{jobId}: serves transcript_deid as transcriptText by default; ?view=raw per contract #3.
GET /transcript/search: keyset pagination on (created_at DESC, id DESC), opaque base64 cursor {t, id}, row-comparison WHERE (created_at, id) < (:t, :id), optional jobStatus/userId filters, limit default 20 max 100. Register /transcript/search before /transcript/{job_id} (route shadowing).
GET /healthz (DB + Redis ping) for compose healthchecks.
Circuit breaker: in-process sliding-window failure rate; trip() (429), half-open probe after cooldown; injectable clock for tests.
PHI-safe logging: log jobId/chunkId only, never transcript text or audio paths.
Deid subsystem (app/deid/) — CIPHER student at take-home scale
Labels: 6 PHI types (NAME, DATE, PHONE, MRN, LOC, AGE), BIO → 13 labels; mask tokens [NAME]… AGE masked unconditionally (recall-first posture).
Model: prajjwal1/bert-tiny encoder + head (Linear→GELU→Dropout→Linear→13) + CRF (learned transitions; constraint mask −1e4, never −inf, so logsumexp can't NaN; I-X only after B-X/I-X; I-X can't start).
Viterbi (viterbi.py): vectorized batched decode — one Python loop over T of pure tensor ops, preallocated backpointers, single .cpu() at the end; plus brute_force_decode for tests.
Losses (losses.py): focal soft CE with p̂_t = student prob of teacher-argmax label, detached in the weight (1−p̂_t)^γ, γ=2; combined α·ℒ_distill + (1−α)·ℒ_CRF (CRF NLL on argmax labels), α=0.5; ablation flags --hard-labels --gamma 0 --no-crf-loss.
Teacher: K=5 deliberately-varied rule/gazetteer annotators over synthetic data with gold spans (controlled perturbations: title inclusion, bare-year DATE, over-extended phones, smaller name gazetteer, "of <City>" LOC) → genuine boundary disagreement → fractional soft labels. CPU-free, deterministic, minutes to train — the pragmatic substitute for the paper's LLM ensemble (rejected alternative documented).
Data (data/): ~50 templates × 4 families (dialogue, intake, narrative, PHI-free hard negatives — lab values, doses, eponyms, since bert-tiny is uncased), Faker fillers with seeded RNG, spans recorded during string assembly (correct by construction). Outlier-aware sampling: 14 lexical features, robust Z (MAD), 2,500 candidates → 90% stratified + 10% |z|>2 oversample → 2,000 train docs; 300 val; 150 entity-dense eval docs (≥40 instances/type — makes the recall number meaningful and the demo transcript visually saturated).
Inference (inference.py + masking.py): sentence-segment to ≤128 wordpieces, batch-tokenize with fast tokenizer return_offsets_mapping=True, one forward + one batched Viterbi, BIO→char spans (open at B-X or orphan I-X — recall-first repair), whitespace-merge, rebuild masked string from slices. masking.py is torch-free pure string logic. Target: <200 ms for a 4,000-word doc on CPU.
Training: python -m app.deidentification.train (AdamW, 4 epochs, batch 32, lr head 5e-4 / encoder 1e-4, seed 13) ≈ 2–5 min CPU. Artifacts committed to the repo (~18 MB student.pt + config.json + metrics.json with the paper's 19-pt synthetic-only caveat printed verbatim) so the demo works on first clone; make deid regenerates from scratch. Acceptance gate: eval_dense recall ≥ 0.90, per-type ≥ 0.85; if short, fall back to unioning model spans with high-precision PHONE/MRN/DATE regexes behind a flag (defensible per §11 recall-first).
Frontend — React demo console
Stack: Vite + TS + Tailwind v4 (@theme block pasted verbatim from frontend-design.txt; Google Fonts in index.html; theme-color #F3ECDC; no component library). Codegen: openapi-typescript → committed schema.d.ts + openapi-fetch typed client (baseUrl: "", same-origin everywhere).
Routes: / Submit, /jobs/:jobId JobDetail, /search — under an AppShell (1320px, sticky ~11.5rem left nav, hairline dividers, mono uppercase labels).
Submit: entry/list grid pattern (grid-cols-[80px_1fr], mono teal ordinals), hand-rolled checkboxes, poison chunk row tagged "ALWAYS FAILS" + the labeled "include a chunk that always fails" checkbox two-way synced to it; userId input defaulting demo-user; Idempotency-Key = crypto.randomUUID() per form session; navigate to job page on 202.
JobDetail (demo centerpiece): evidence-card row (chunks/completed/status/completedAt — serif numbers, mono labels, tabular-nums); ChunkStatusStrip — equal-width hairline cells from the chunks array, status word colored per the semantic map (PENDING faint / PROCESSING teal + subtle pulse / COMPLETED green / FAILED accent), attempt dots + ×n counter; MaskedTranscript — parses mask tokens and [chunk N unavailable] gap markers into highlighted chips-in-prose with data-mask attributes (Playwright hook) and a derived legend; "show raw" toggle (audit-logged, terminal-only, never polled) with elevated-state accent border. Polling: TanStack v5 refetchInterval: (q) => isTerminal(q.state.data?.jobStatus) ? false : 1000 — stops permanently at terminal state; 404-retry ×3 absorbs the submit→read race; during the kill-the-worker demo the strip visibly stalls then recovers.
Search: status filter chips + userId input, state in URL params; useInfiniteQuery with getNextPageParam: (last) => last.nextCursor ?? undefined; IntersectionObserver sentinel; entry/list rows linking to job pages; mono "— end of record —".
Docker: multi-stage node→nginx; nginx proxies /transcribe and /transcript to api:8000, SPA fallback. Vite dev proxy mirrors the same two roots.
docker-compose
Services: postgres:16-alpine (healthcheck), redis:7-alpine (healthcheck), migrate (one-shot alembic upgrade head), api (uvicorn :8000), worker (arq app.workers.main.WorkerSettings, no restart policy on purpose — kill -9 stays dead until restarted, which is the demo), mock-asr (provided; port confirmed from its source), frontend (nginx, e.g. 5173:80). Shared env anchor: DATABASE_URL, REDIS_URL, ASR_BASE_URL, ASR_MAX_CONCURRENCY=90; full knob surface (ASR_LEASE_TTL_SECONDS=30, ASR_TIMEOUT_SECONDS=15, RETRY_MAX_ATTEMPTS=4, RETRY_BASE_DELAY=0.5, RETRY_MAX_DELAY=8, CHUNK_STUCK_SECONDS=120, RECONCILER_INTERVAL_SECONDS=60, breaker thresholds) in config.py + .env.example.

Build order (each milestone leaves docker compose up demoable)
Backend core

Scaffold: pyproject, config, Dockerfile, compose (pg+redis), logging, healthz. Verify: healthz green.
Models + 0001_initial. Verify: upgrade/downgrade round-trip; \d shows indexes.
API without workers (transcribe insert-only, GET, search, idempotency, cursor). Verify: unit tests + curl POST→202, double-POST same key → same jobId.
Confirm mock-asr contract (run it, read its source), then asr_client + retry + breaker. Verify: respx tests + live smoke against the mock.
Semaphore (Lua). Verify: fakeredis cap-under-contention test; real-Redis hammer script shows hwm ≤ 90.
Worker happy path (process_chunk without failure branches, finish_chunk, stitch with identity-deid stub). Verify: 6-chunk job → COMPLETED ~10 s; concurrent finish_chunk race test — exactly one sees 0.
Failure taxonomy (retry/404/exhaustion/429/no-permit). Verify: permit released on every exit path (ZCARD==0); poison chunk e2e → COMPLETED_WITH_ERRORS, attempts=4, marker inline.
Reconciler + crash recovery. Verify: manual docker compose kill -s SIGKILL worker → restart → completes; then automated e2e.
Concurrency proof e2e: ~40 jobs × 8 chunks burst; assert semaphore hwm ≤ 90 (+ mock max-in-flight ≤ 100 if exposed); all jobs terminal.
Deid (parallelizable with backend 4–9; integrates at step 15) 10. labels + masking (torch-free) → tests. 11. crf + viterbi → vs brute-force tests. 12. losses → hand-computed-value tests. 13. templates/generate/features + teacher → datagen & boundary-disagreement tests. 14. train + eval, run make deid. Verify: eval_dense recall ≥ 0.90 in metrics.json; one --hard-labels ablation for the presentation. 15. inference + swap stitch stub → real deidentify. Verify: e2e job shows masked transcript; audit row on ?view=raw.

Frontend (parallelizable once API shape stabilizes at step 3) 16. Scaffold + theme + AppShell + shared primitives. Verify: parchment page, serif 18px body, no blue focus rings. 17. API layer (codegen, commit schema.d.ts, queries). Verify: tsc clean. 18. Submit page. 19. JobDetail (polling, strip, masked transcript, raw toggle). Verify: watch live fan-out; Network tab shows 1 s polls that stop at terminal; kill-the-worker stall+recovery visible. 20. Search (infinite scroll). Verify: seed ~30 jobs, cursor pages of 20. 21. Docker/nginx + compose integration. 22. Playwright smoke (submit 3 chunks + poison → terminal ≤75 s → data-mask spans + gap marker visible). Verify: green twice in a row.

Finish 23. PHI-log audit (grep: no handler logs transcript/audio paths), README (run instructions, make deid, demo script incl. kill -9 walkthrough), optional k6 smoke.

Top correctness risks (addressed by design)
Double-stitch / no-stitch: decrement only inside the guarded terminal transition's transaction (exactly-once), atomic RETURNING pending_chunks serializes on the row lock (exactly one sees 0), stitch itself idempotent + guarded, reconciler C backstops the commit→enqueue gap.
Permit leaks: release in finally; TTL leases purged by next acquirer using Redis server time; cap 90/100 absorbs the expiry double-count window; tests assert ZCARD==0 after every exit path.
Enqueue-after-commit gap: strict commit→enqueue ordering + reconciler A with deduping arq job ids.
Duplicate ASR spend on redelivery: bounded, not eliminated — CHUNK_STUCK_SECONDS=120 > TTL + max call; both copies need permits so the budget holds; guarded transition means only the first result persists.
Vendor-contract drift: mock shape unverified until in hand; quarantined in asr_client.py, confirmed at milestone 4 before anything depends on it.
Tokenizer offset bugs (deid): only fast-tokenizer offset_mapping ever touches the original string; masking rebuilds from slices; property test text[start:end] == span.text everywhere; segment base offsets added in one tested function.
Tiny-model recall: in-distribution eval + entity-dense set + contextual-cue templates + hard negatives; regex-union fallback flag if the ≥0.90 gate fails; 19-pt synthetic caveat stated honestly.
Verification (end-to-end)
pytest backend/tests — unit (fake-clock retry, fakeredis semaphore, stitcher, cursor, idempotency, Viterbi-vs-brute-force, loss numerics, masking alignment) + integration (testcontainers PG/Redis, respx ASR) all green.
docker compose up → full stack; submit via console; watch fan-out; poison chunk → COMPLETED_WITH_ERRORS with inline marker; masked transcript renders with highlighted spans; ?view=raw writes an audit row.
Crash demo: docker compose kill -s SIGKILL worker mid-job → stall visible in UI → docker compose start worker → job completes.
Concurrency proof e2e: burst load, semaphore high-water mark ≤ 90.
npx playwright test green twice consecutively.
