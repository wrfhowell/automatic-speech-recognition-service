"""De-identification stage contract.

stitch_job depends only on this interface: deidentify(text) -> DeidResult.
Currently an identity stub; replaced by the CIPHER student model (M10-M15).
"""

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


def deidentify(text: str) -> DeidResult:
    return DeidResult(masked_text=text)
