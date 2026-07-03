"""The ONLY module that knows the ASR vendor's wire contract.

Verified against the provided mock (mock-asr/asr-server.js):
  GET {base_url}/get-asr-output?path=<audio_path>
    200 -> {"path": ..., "transcript": ...}
    404 -> unknown path (permanent)
    500 -> shouldError or random 1/20 (transient)
    429 -> >100 concurrent requests (our limiter invariant is broken)
  Latency: uniform 5-10 s.
"""

from dataclasses import dataclass
from enum import StrEnum

import httpx


class AsrKind(StrEnum):
    OK = "OK"
    NOT_FOUND = "NOT_FOUND"
    TRANSIENT = "TRANSIENT"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass(frozen=True)
class AsrResult:
    kind: AsrKind
    transcript: str | None = None
    detail: str = ""


class AsrClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout_seconds)
        )

    async def get_transcript(self, audio_path: str) -> AsrResult:
        try:
            resp = await self._client.get("/get-asr-output", params={"path": audio_path})
        except httpx.TimeoutException:
            return AsrResult(AsrKind.TRANSIENT, detail="timeout")
        except httpx.TransportError as exc:
            return AsrResult(AsrKind.TRANSIENT, detail=f"transport: {type(exc).__name__}")

        if resp.status_code == 200:
            return AsrResult(AsrKind.OK, transcript=resp.json()["transcript"])
        if resp.status_code == 404:
            return AsrResult(AsrKind.NOT_FOUND, detail="http 404")
        if resp.status_code == 429:
            return AsrResult(AsrKind.RATE_LIMITED, detail="http 429")
        return AsrResult(AsrKind.TRANSIENT, detail=f"http {resp.status_code}")

    async def aclose(self) -> None:
        await self._client.aclose()
