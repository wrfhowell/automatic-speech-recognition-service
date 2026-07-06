"""Stitch -> real CIPHER student -> masked transcript_deid.

The one integration test that runs the committed model (everything else
patches deid to identity — see conftest). Skips until artifacts exist.
"""

import pytest
from sqlalchemy import select

from app.deidentification.model import ARTIFACTS_DIR
from app.models import Chunk, Job
from app.workers.stitch_job import stitch_job

from .conftest import seed_job_with_chunks

pytestmark = [
    pytest.mark.real_deid,
    pytest.mark.skipif(
        not (ARTIFACTS_DIR / "student.pt").exists(),
        reason="deid artifacts not built (run `make deid`)",
    ),
]

CHUNK_TEXTS = [
    "doctor: good morning Jane Smith, how have you been feeling since 03/14/2024?",
    "patient: better. you can reach me at 555-201-8890 if anything changes.",
]


async def test_stitch_masks_phi_and_preserves_raw(app, worker_ctx):
    job_id, chunk_ids = await seed_job_with_chunks(
        app, chunk_statuses=["COMPLETED", "COMPLETED"]
    )
    async with app.state.sessionmaker() as session:
        chunks = (
            await session.scalars(select(Chunk).where(Chunk.job_id == job_id))
        ).all()
        for chunk in sorted(chunks, key=lambda c: c.ordinal):
            chunk.transcript_text = CHUNK_TEXTS[chunk.ordinal]
        await session.commit()

    await stitch_job(worker_ctx, str(job_id))

    async with app.state.sessionmaker() as session:
        job = await session.get(Job, job_id)
    assert job.status == "COMPLETED"
    assert job.transcript_text == "\n\n".join(CHUNK_TEXTS)  # raw untouched

    deid = job.transcript_deid
    assert "Jane Smith" not in deid
    assert "555-201-8890" not in deid
    assert "03/14/2024" not in deid
    assert "[NAME]" in deid and "[PHONE]" in deid and "[DATE]" in deid
    # Non-PHI prose survives byte-for-byte.
    assert "how have you been feeling since" in deid
    assert "if anything changes." in deid
