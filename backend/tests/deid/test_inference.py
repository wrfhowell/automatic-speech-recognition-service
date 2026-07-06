"""Segmentation + end-to-end inference against the committed artifacts.

Everything here skips if artifacts/ hasn't been built yet (make deid);
once artifacts are committed these run everywhere.
"""

import json
import time

import pytest

from app.deidentification.model import ARTIFACTS_DIR

pytestmark = pytest.mark.skipif(
    not (ARTIFACTS_DIR / "student.pt").exists(),
    reason="deid artifacts not built (run `make deid`)",
)


@pytest.fixture(scope="module")
def deid():
    from app.deidentification.inference import Deidentifier

    return Deidentifier.from_artifacts()


SAMPLE = (
    "doctor: good morning Jane Smith, how have you been feeling since 03/14/2024?\n"
    "patient: better. my number is 555-201-8890 and my mrn is 4821736.\n"
    "blood pressure was 132 over 84 with a heart rate of 78."
)


def test_segments_tile_text_with_correct_base_offsets(deid):
    from app.deidentification.inference import MAX_WORDPIECES, segment_text

    long_text = SAMPLE * 20
    segments = segment_text(long_text, deid.tokenizer)
    assert "".join(seg for seg, _ in segments) == long_text
    for seg, base in segments:
        assert long_text[base : base + len(seg)] == seg
        n = len(deid.tokenizer(seg)["input_ids"])  # includes [CLS]/[SEP]
        assert n <= MAX_WORDPIECES


def test_oversized_unpunctuated_sentence_is_split(deid):
    from app.deidentification.inference import MAX_WORDPIECES, segment_text

    blob = "lorem ipsum dolor sit amet " * 60  # no sentence boundaries at all
    segments = segment_text(blob, deid.tokenizer)
    assert len(segments) > 1
    assert "".join(seg for seg, _ in segments) == blob
    for seg, _ in segments:
        assert len(deid.tokenizer(seg)["input_ids"]) <= MAX_WORDPIECES


def test_spans_are_sorted_disjoint_and_in_bounds(deid):
    result = deid(SAMPLE)
    prev_end = 0
    for span in result.spans:
        assert 0 <= span.start < span.end <= len(SAMPLE)
        assert span.start >= prev_end
        prev_end = span.end


def test_non_phi_text_survives_byte_for_byte(deid):
    result = deid(SAMPLE)
    # Rebuild the original around the masks: every inter-span slice of the
    # original must appear verbatim, in order, in the masked text.
    cursor = 0
    pos = 0
    for span in result.spans:
        keep = SAMPLE[cursor : span.start]
        found = result.masked_text.find(keep, pos)
        assert found != -1
        pos = found + len(keep)
        cursor = span.end
    assert SAMPLE[cursor:] == "" or SAMPLE[cursor:] in result.masked_text[pos:]


def test_empty_and_whitespace_input_pass_through(deid):
    assert deid("").masked_text == ""
    assert deid("   \n ").masked_text == "   \n "


def test_committed_metrics_pass_recall_gate():
    from app.deidentification.eval import passes_gate

    metrics = json.loads((ARTIFACTS_DIR / "metrics.json").read_text())
    assert passes_gate(metrics), metrics["per_type_recall"]


def test_live_recall_on_dense_sample(deid):
    from app.deidentification.data.generate import generate_dense_eval
    from app.deidentification.eval import evaluate

    config = json.loads((ARTIFACTS_DIR / "config.json").read_text())
    docs = generate_dense_eval(config["n_eval_dense"], seed=config["seed_eval"])[:20]
    metrics = evaluate(deid.predict_spans, docs)
    assert metrics["overall_recall"] >= 0.85, metrics


def test_latency_4000_word_doc(deid):
    words = SAMPLE.split()
    doc = " ".join(words * (4000 // len(words) + 1))
    deid(doc)  # warm
    started = time.perf_counter()
    deid(doc)
    elapsed = time.perf_counter() - started
    # Plan target is <200 ms; assert a generous CI-safe bound and print.
    print(f"4000-word doc: {elapsed * 1000:.0f} ms")
    assert elapsed < 1.0
