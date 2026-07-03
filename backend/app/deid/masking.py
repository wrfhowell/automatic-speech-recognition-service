"""Pure string logic: BIO token labels -> character spans -> masked text.

Torch-free by design. The masked string is rebuilt from slices of the
original text, so every non-PHI character is preserved byte-for-byte —
masking is span-replacement, never generative (§8.3)."""

from app.deid import PhiSpan
from app.deid.labels import mask_token


def bio_to_spans(
    labels: list[str],
    offsets: list[tuple[int, int]],
    base_offset: int = 0,
) -> list[PhiSpan]:
    """Collapse per-token BIO labels into character spans.

    Recall-first repair: a span opens at B-X or at an orphan I-X (an I with
    no matching open entity) — a boundary mistake by the model must not
    leak the tail of a name."""
    spans: list[PhiSpan] = []
    open_label: str | None = None
    open_start = 0
    open_end = 0

    def close() -> None:
        nonlocal open_label
        if open_label is not None:
            spans.append(PhiSpan(open_start, open_end, open_label))
            open_label = None

    for label, (start, end) in zip(labels, offsets):
        if start == end:  # special/pad token
            continue
        if label == "O":
            close()
            continue
        prefix, entity = label.split("-", 1)
        if prefix == "I" and open_label == entity:
            open_end = base_offset + end
        else:  # B-X, or orphan I-X treated as an opener
            close()
            open_label = entity
            open_start = base_offset + start
            open_end = base_offset + end
    close()
    return spans


def merge_spans(spans: list[PhiSpan], text: str) -> list[PhiSpan]:
    """Sort, then merge same-label spans separated only by whitespace (the
    tokenizer splits 'jane smith' in two) and clamp any overlap."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    merged = [ordered[0]]
    for span in ordered[1:]:
        prev = merged[-1]
        gap_is_ws = span.start >= prev.end and text[prev.end : span.start].strip() == ""
        if span.label == prev.label and (span.start <= prev.end or gap_is_ws):
            merged[-1] = PhiSpan(prev.start, max(prev.end, span.end), prev.label)
        elif span.start < prev.end:
            if span.end > prev.end:  # different label, partial overlap: clamp
                merged.append(PhiSpan(prev.end, span.end, span.label))
            # fully contained in prev: drop
        else:
            merged.append(span)
    return merged


def apply_masks(text: str, spans: list[PhiSpan]) -> str:
    """Rebuild the string from slices with [TYPE] tokens over the spans.
    Expects sorted, non-overlapping spans (merge_spans output)."""
    parts: list[str] = []
    cursor = 0
    for span in spans:
        parts.append(text[cursor : span.start])
        parts.append(mask_token(span.label))
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts)
