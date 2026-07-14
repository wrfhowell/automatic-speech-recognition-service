"""De-identification stage contract.

stitch_job depends only on this interface: deidentify(text) -> DeidResult.
The CIPHER student loads lazily behind a per-process singleton, so
importing app.deidentification stays cheap (no torch) until the first real call.
"""

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PhiSpan:
    start: int
    end: int
    label: str


@dataclass(frozen=True)
class DeidResult:
    masked_text: str
    spans: list[PhiSpan] = field(default_factory=list)


_deidentifier = None
_load_lock = threading.Lock()
# The HF fast tokenizer (and the shared model) are not thread-safe: concurrent
# calls raise "Already borrowed" from the tokenizer's Rust core. Stitch tasks
# call deidentify from worker threads (asyncio.to_thread), so inference is
# serialized per process — it's a single CPU-bound model either way.
_infer_lock = threading.Lock()


def deidentify(text: str) -> DeidResult:
    global _deidentifier
    if _deidentifier is None:
        with _load_lock:
            if _deidentifier is None:
                from app.deidentification.inference import Deidentifier

                _deidentifier = Deidentifier.from_artifacts()
    with _infer_lock:
        return _deidentifier(text)
