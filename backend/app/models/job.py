import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Integer, Text, Uuid, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import JobStatus


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=JobStatus.PENDING.value
    )
    # Stitch-trigger counter, seeded to the chunk count at submit time and
    # atomically decremented as each chunk reaches a terminal state; exactly
    # one decrementer observes 0 and enqueues the stitch.
    pending_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    transcript_deid: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','COMPLETED','COMPLETED_WITH_ERRORS','FAILED')",
            name="jobs_status_check",
        ),
        # Keyset-pagination orderings for /transcript/search filter combos
        Index(
            "ix_jobs_user_status_created",
            "user_id", "status", text("created_at DESC"), text("id DESC"),
        ),
        Index("ix_jobs_status_created", "status", text("created_at DESC"), text("id DESC")),
        Index("ix_jobs_created", text("created_at DESC"), text("id DESC")),
    )
