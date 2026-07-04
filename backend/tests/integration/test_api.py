import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import AuditLog, Chunk, Job, JobStatus


async def _seed_job(
    app,
    *,
    user_id="u1",
    status=JobStatus.PENDING.value,
    created_at=None,
    transcript_deid=None,
    n_chunks=0,
):
    async with app.state.sessionmaker() as session:
        job = Job(
            user_id=user_id,
            status=status,
            pending_chunks=n_chunks,
            transcript_deid=transcript_deid,
        )
        if created_at is not None:
            job.created_at = created_at
        session.add(job)
        await session.flush()
        for i in range(n_chunks):
            session.add(
                Chunk(job_id=job.id, ordinal=i, audio_path=f"audio-file-{i + 1}.wav")
            )
        await session.commit()
        return job.id


async def test_submit_returns_202_and_creates_rows(client, app):
    resp = await client.post(
        "/transcribe",
        json={"audioChunkPaths": ["audio-file-1.wav", "audio-file-2.wav"], "userId": "u1"},
    )
    assert resp.status_code == 202
    job_id = uuid.UUID(resp.json()["jobId"])

    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        assert job.status == "PENDING"
        assert job.pending_chunks == 2
        chunks = (
            await session.scalars(
                select(Chunk).where(Chunk.job_id == job_id).order_by(Chunk.ordinal)
            )
        ).all()
        assert [c.audio_path for c in chunks] == ["audio-file-1.wav", "audio-file-2.wav"]
        assert all(c.status == "PENDING" for c in chunks)


async def test_idempotent_double_post_returns_same_job(client, app):
    body = {"audioChunkPaths": ["audio-file-1.wav"], "userId": "u1"}
    headers = {"Idempotency-Key": "key-123"}
    first = await client.post("/transcribe", json=body, headers=headers)
    second = await client.post("/transcribe", json=body, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["jobId"] == second.json()["jobId"]

    async with app.state.sessionmaker() as session:
        assert (await session.scalar(select(func.count()).select_from(Job))) == 1
        assert (await session.scalar(select(func.count()).select_from(Chunk))) == 1


async def test_posts_without_key_create_separate_jobs(client, app):
    body = {"audioChunkPaths": ["audio-file-1.wav"], "userId": "u1"}
    first = await client.post("/transcribe", json=body)
    second = await client.post("/transcribe", json=body)
    assert first.json()["jobId"] != second.json()["jobId"]


async def test_get_unknown_job_404(client):
    resp = await client.get(f"/transcript/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_get_transcript_shape(client, app):
    job_id = await _seed_job(app, n_chunks=3, transcript_deid=None)
    resp = await client.get(f"/transcript/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["jobId"] == str(job_id)
    assert data["jobStatus"] == "PENDING"
    assert data["transcriptText"] is None
    assert data["completedTime"] is None
    assert data["chunkStatuses"] == {
        "audio-file-1.wav": "PENDING",
        "audio-file-2.wav": "PENDING",
        "audio-file-3.wav": "PENDING",
    }
    assert [c["ordinal"] for c in data["chunks"]] == [0, 1, 2]
    assert all(c["attempts"] == 0 for c in data["chunks"])


async def test_default_view_serves_deid_and_raw_view_audits(client, app):
    job_id = await _seed_job(
        app, status=JobStatus.COMPLETED.value, transcript_deid="[NAME] visited."
    )
    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
        job.transcript_text = "Sarah visited."
        await session.commit()

    default = await client.get(f"/transcript/{job_id}")
    assert default.json()["transcriptText"] == "[NAME] visited."

    raw = await client.get(f"/transcript/{job_id}", params={"view": "raw"})
    assert raw.json()["transcriptText"] == "Sarah visited."

    async with app.state.sessionmaker() as session:
        rows = (await session.scalars(select(AuditLog))).all()
        assert len(rows) == 1
        assert rows[0].job_id == job_id
        assert rows[0].action == "RAW_READ"


async def test_search_keyset_pagination(client, app):
    base = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    ids = []
    for i in range(45):
        ids.append(
            await _seed_job(app, created_at=base + timedelta(seconds=i), user_id="u1")
        )

    seen = []
    cursor = None
    for _ in range(3):
        params = {"limit": 20}
        if cursor:
            params["cursor"] = cursor
        resp = await client.get("/transcript/search", params=params)
        assert resp.status_code == 200
        page = resp.json()
        seen.extend(r["jobId"] for r in page["results"])
        cursor = page.get("nextCursor")
        if cursor is None:
            break

    assert cursor is None
    assert len(seen) == 45
    assert len(set(seen)) == 45
    # newest first
    assert seen[0] == str(ids[-1])
    assert seen[-1] == str(ids[0])


async def test_search_filters(client, app):
    await _seed_job(app, user_id="alice", status="COMPLETED")
    await _seed_job(app, user_id="alice", status="FAILED")
    await _seed_job(app, user_id="bob", status="COMPLETED")

    resp = await client.get(
        "/transcript/search", params={"userId": "alice", "jobStatus": "COMPLETED"}
    )
    results = resp.json()["results"]
    assert len(results) == 1
    assert results[0]["userId"] == "alice"
    assert results[0]["jobStatus"] == "COMPLETED"


async def test_search_rejects_bad_inputs(client):
    assert (await client.get("/transcript/search", params={"jobStatus": "NOPE"})).status_code == 400
    assert (await client.get("/transcript/search", params={"cursor": "garbage"})).status_code == 400
    assert (await client.get("/transcript/search", params={"limit": 101})).status_code == 422
