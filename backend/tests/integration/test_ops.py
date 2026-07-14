"""GET /ops exposes the operational counters the demo and load test lean on:
semaphore held/high-water-mark (the vendor-cap evidence), arq queue depth,
job/chunk status counts, and job latency percentiles. Numbers only — no
transcript text or audio paths ever appear here."""

from datetime import UTC, datetime, timedelta

import pytest
from arq.constants import default_queue_name

from app.core.semaphore import HWM_KEY, LEASES_KEY
from app.models import Chunk, Job, JobStatus


async def _seed_job(app, *, status, created_at=None, completed_time=None, chunks=()):
    """chunks: iterable of (status, attempts)."""
    async with app.state.sessionmaker() as session:
        job = Job(user_id="ops-test", status=status, pending_chunks=len(chunks))
        if created_at is not None:
            job.created_at = created_at
        job.completed_time = completed_time
        session.add(job)
        await session.flush()
        for i, (chunk_status, attempts) in enumerate(chunks):
            session.add(
                Chunk(
                    job_id=job.id,
                    ordinal=i,
                    audio_path=f"audio-file-{i + 1}.wav",
                    status=chunk_status,
                    attempts=attempts,
                )
            )
        await session.commit()
        return job.id


async def test_ops_reports_semaphore_queue_and_db_counters(client, app):
    redis = app.state.redis
    now = datetime.now(UTC).timestamp()
    await redis.zadd(
        LEASES_KEY, {"lease-1": now + 30, "lease-2": now + 30, "lease-3": now + 30}
    )
    await redis.set(HWM_KEY, 74)
    await redis.rpush(default_queue_name, "job-a", "job-b")

    base = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    await _seed_job(
        app,
        status=JobStatus.COMPLETED.value,
        created_at=base,
        completed_time=base + timedelta(seconds=10),
    )
    await _seed_job(
        app,
        status=JobStatus.COMPLETED.value,
        created_at=base,
        completed_time=base + timedelta(seconds=20),
    )
    await _seed_job(
        app,
        status=JobStatus.PROCESSING.value,
        chunks=[("COMPLETED", 1), ("PENDING", 2)],
    )

    resp = await client.get("/ops")
    assert resp.status_code == 200
    data = resp.json()

    assert data["semaphore"] == {"held": 3, "highWaterMark": 74, "capacity": 90}
    assert data["queue"] == {"depth": 2}
    assert data["jobs"] == {"COMPLETED": 2, "PROCESSING": 1}
    assert data["chunks"]["byStatus"] == {"COMPLETED": 1, "PENDING": 1}
    assert data["chunks"]["totalRetries"] == 3
    assert data["latency"]["completedJobs"] == 2
    assert data["latency"]["p50Seconds"] == pytest.approx(15.0)
    assert data["latency"]["p95Seconds"] == pytest.approx(19.5)


async def test_loadtest_submits_burst_and_resets_hwm(client, app):
    from sqlalchemy import select

    await app.state.redis.set(HWM_KEY, 74)  # stale mark from a previous burst

    resp = await client.post("/ops/loadtest", json={"jobs": 3, "chunks": 2})
    assert resp.status_code == 202
    assert resp.json() == {"jobsSubmitted": 3, "chunksSubmitted": 6}

    # The mark is reset so the new burst is measured from zero.
    assert await app.state.redis.get(HWM_KEY) is None

    async with app.state.sessionmaker() as session:
        jobs = (
            (await session.execute(select(Job).where(Job.user_id == "loadtest")))
            .scalars()
            .all()
        )
        assert len(jobs) == 3
        assert all(j.status == JobStatus.PENDING.value for j in jobs)
        chunk_count = len(
            (await session.execute(select(Chunk))).scalars().all()
        )
        assert chunk_count == 6


async def test_loadtest_rejects_out_of_range_burst(client):
    resp = await client.post("/ops/loadtest", json={"jobs": 0, "chunks": 2})
    assert resp.status_code == 422
    resp = await client.post("/ops/loadtest", json={"jobs": 3, "chunks": 99})
    assert resp.status_code == 422


async def test_ops_empty_state_serves_zeros_not_errors(client):
    resp = await client.get("/ops")
    assert resp.status_code == 200
    data = resp.json()
    assert data["semaphore"] == {"held": 0, "highWaterMark": 0, "capacity": 90}
    assert data["queue"] == {"depth": 0}
    assert data["jobs"] == {}
    assert data["chunks"] == {"byStatus": {}, "totalRetries": 0}
    assert data["latency"] == {
        "completedJobs": 0,
        "p50Seconds": None,
        "p95Seconds": None,
    }
