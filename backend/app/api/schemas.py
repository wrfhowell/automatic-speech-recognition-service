import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TranscribeRequest(ApiModel):
    audio_chunk_paths: list[str] = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1)

    @field_validator("audio_chunk_paths")
    @classmethod
    def paths_non_empty(cls, v: list[str]) -> list[str]:
        stripped = [p.strip() for p in v]
        if any(not p for p in stripped):
            raise ValueError("audio chunk paths must be non-empty")
        return stripped


class TranscribeResponse(ApiModel):
    job_id: uuid.UUID


class ChunkInfo(ApiModel):
    ordinal: int
    audio_path: str
    status: str
    attempts: int


class TranscriptResult(ApiModel):
    job_id: uuid.UUID
    user_id: str
    transcript_text: str | None
    # Contract-faithful map per DESIGN.md §3; `chunks` adds ordering and
    # attempt counts for the console UI.
    chunk_statuses: dict[str, str]
    chunks: list[ChunkInfo]
    job_status: str
    completed_time: datetime | None


class SearchResponse(ApiModel):
    results: list[TranscriptResult]
    next_cursor: str | None = None


class SemaphoreStats(ApiModel):
    held: int
    high_water_mark: int
    capacity: int


class QueueStats(ApiModel):
    depth: int


class ChunkStats(ApiModel):
    by_status: dict[str, int]
    total_retries: int


class LatencyStats(ApiModel):
    completed_jobs: int
    p50_seconds: float | None
    p95_seconds: float | None


class LoadTestRequest(ApiModel):
    jobs: int = Field(default=40, ge=1, le=100)
    chunks: int = Field(default=8, ge=1, le=8)


class LoadTestResponse(ApiModel):
    jobs_submitted: int
    chunks_submitted: int


class OpsResponse(ApiModel):
    semaphore: SemaphoreStats
    queue: QueueStats
    jobs: dict[str, int]
    chunks: ChunkStats
    latency: LatencyStats
