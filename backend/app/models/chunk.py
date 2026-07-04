import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import ChunkStatus


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default=ChunkStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    transcript_text: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    # Touched on every transition; doubles as the reconciler heartbeat.
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','COMPLETED','FAILED')",
            name="chunks_status_check",
        ),
        # Also serves job_id lookups (leftmost prefix), so no separate
        # chunks(job_id) index.
        UniqueConstraint("job_id", "ordinal", name="uq_chunks_job_ordinal"),
        # Reconciler scan: only non-terminal chunks are ever interesting.
        Index(
            "ix_chunks_nonterminal_updated",
            "status", "updated_at",
            postgresql_where=text("status IN ('PENDING','PROCESSING')"),
        ),
    )
