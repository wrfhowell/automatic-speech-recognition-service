"""Inference: text -> masked text + spans.

Pipeline: sentence-segment to <=128 wordpieces, batch-tokenize with the
fast tokenizer's offset mapping (the ONLY thing that ever maps tokens back
to the original string), one forward pass + one batched Viterbi decode,
BIO -> char spans per segment (base offsets added here), whitespace-merge,
rebuild the masked string from slices.
"""

import re
from pathlib import Path

import torch
from transformers import AutoTokenizer, PreTrainedTokenizerFast

from app.deid import DeidResult, PhiSpan
from app.deid.labels import ID_TO_LABEL
from app.deid.masking import apply_masks, bio_to_spans, merge_spans
from app.deid.model import ARTIFACTS_DIR, DeidStudent, load_student

MAX_WORDPIECES = 128  # per segment, including [CLS]/[SEP]

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentence_pieces(text: str) -> list[tuple[int, int]]:
    """(start, end) sentence-ish pieces that exactly tile the text."""
    pieces = []
    cursor = 0
    for m in _SENTENCE_BOUNDARY.finditer(text):
        pieces.append((cursor, m.end()))
        cursor = m.end()
    if cursor < len(text):
        pieces.append((cursor, len(text)))
    return [p for p in pieces if p[0] < p[1]]


def _split_oversized(
    text: str, start: int, end: int, tokenizer: PreTrainedTokenizerFast, budget: int
) -> list[tuple[int, int]]:
    """A single sentence longer than the budget: cut at wordpiece boundaries."""
    enc = tokenizer(text[start:end], add_special_tokens=False, return_offsets_mapping=True)
    offsets = enc["offset_mapping"]
    pieces = []
    for i in range(0, len(offsets), budget):
        window = offsets[i : i + budget]
        piece_start = start + window[0][0]
        piece_end = start + window[-1][1]
        pieces.append((piece_start, piece_end))
    # Wordpiece offsets skip inter-token whitespace; stretch each piece to
    # meet the next so the segments still tile the text.
    stretched = []
    for j, (s, e) in enumerate(pieces):
        nxt = pieces[j + 1][0] if j + 1 < len(pieces) else end
        stretched.append((s, nxt))
    return stretched


def segment_text(
    text: str, tokenizer: PreTrainedTokenizerFast, max_wordpieces: int = MAX_WORDPIECES
) -> list[tuple[str, int]]:
    """-> [(segment, base_offset)]. Segments tile the text in order; each
    fits in max_wordpieces once [CLS]/[SEP] are added."""
    budget = max_wordpieces - 2
    sized: list[tuple[int, int, int]] = []  # (start, end, n_wordpieces)
    for start, end in _sentence_pieces(text):
        n = len(tokenizer(text[start:end], add_special_tokens=False)["input_ids"])
        if n > budget:
            for s, e in _split_oversized(text, start, end, tokenizer, budget):
                sized.append((s, e, budget))
        else:
            sized.append((start, end, n))

    segments: list[tuple[str, int]] = []
    seg_start: int | None = None
    seg_end = 0
    seg_tokens = 0
    for start, end, n in sized:
        if seg_start is not None and seg_tokens + n > budget:
            segments.append((text[seg_start:seg_end], seg_start))
            seg_start = None
        if seg_start is None:
            seg_start, seg_tokens = start, 0
        seg_end, seg_tokens = end, seg_tokens + n
    if seg_start is not None:
        segments.append((text[seg_start:seg_end], seg_start))
    return segments


class Deidentifier:
    def __init__(self, model: DeidStudent, tokenizer: PreTrainedTokenizerFast) -> None:
        self.model = model.eval()
        self.tokenizer = tokenizer

    @classmethod
    def from_artifacts(cls, artifacts_dir: Path = ARTIFACTS_DIR) -> "Deidentifier":
        tokenizer = AutoTokenizer.from_pretrained(artifacts_dir / "tokenizer")
        return cls(load_student(artifacts_dir), tokenizer)

    def predict_spans(self, text: str) -> list[PhiSpan]:
        segments = segment_text(text, self.tokenizer)
        if not segments:
            return []
        enc = self.tokenizer(
            [seg for seg, _ in segments],
            return_offsets_mapping=True,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=MAX_WORDPIECES,
        )
        with torch.no_grad():
            emissions = self.model(enc["input_ids"], enc["attention_mask"])
        paths = self.model.decode(emissions, enc["attention_mask"])

        spans: list[PhiSpan] = []
        offset_rows = enc["offset_mapping"].tolist()
        for (_, base), path, offsets in zip(segments, paths, offset_rows):
            labels = [ID_TO_LABEL[i] for i in path]
            # Padding is on the right, so the first len(path) offsets are
            # exactly the attended tokens; (0,0) specials are skipped inside.
            spans.extend(bio_to_spans(labels, offsets[: len(path)], base_offset=base))
        return merge_spans(spans, text)

    def __call__(self, text: str) -> DeidResult:
        if not text.strip():
            return DeidResult(masked_text=text)
        spans = self.predict_spans(text)
        return DeidResult(masked_text=apply_masks(text, spans), spans=spans)
