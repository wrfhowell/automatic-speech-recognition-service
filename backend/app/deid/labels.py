"""PHI label space: 6 types, BIO scheme -> 13 labels.

Recall-first posture: every detected span is masked unconditionally —
including AGE, where HIPAA Safe Harbor only requires ages > 89. A missed
name is far worse than an over-masked age (§11).

Torch-free: the transition/start masks are plain lists; crf.py turns them
into tensors.
"""

PHI_TYPES = ["NAME", "DATE", "PHONE", "MRN", "LOC", "AGE"]

LABELS = ["O"] + [f"{prefix}-{t}" for t in PHI_TYPES for prefix in ("B", "I")]
LABEL_TO_ID = {label: i for i, label in enumerate(LABELS)}
ID_TO_LABEL = dict(enumerate(LABELS))
NUM_LABELS = len(LABELS)  # 13
O_ID = LABEL_TO_ID["O"]


def mask_token(phi_type: str) -> str:
    return f"[{phi_type}]"


def _entity_type(label: str) -> str | None:
    return None if label == "O" else label.split("-", 1)[1]


def allowed_transitions() -> list[list[bool]]:
    """allowed[i][j]: may label j follow label i? I-X only after B-X/I-X."""
    allowed = [[True] * NUM_LABELS for _ in range(NUM_LABELS)]
    for i, from_label in enumerate(LABELS):
        for j, to_label in enumerate(LABELS):
            if to_label.startswith("I-") and _entity_type(from_label) != _entity_type(to_label):
                allowed[i][j] = False
    return allowed


def allowed_starts() -> list[bool]:
    """I-X can never start a sequence."""
    return [not label.startswith("I-") for label in LABELS]
