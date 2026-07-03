import re

from app.deid.data.generate import generate_corpus
from app.deid.labels import LABEL_TO_ID, O_ID
from app.deid.teacher import K, annotate_ensemble, soft_labels, spans_to_bio_ids


def _whitespace_offsets(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def test_annotators_disagree_on_title_boundaries():
    text = "the patient was seen in clinic by dr. Sarah Johnson on march 3, 2024."
    per_annotator = annotate_ensemble(text)
    name_spans = {
        (s, e) for spans in per_annotator for (s, e, label) in spans if label == "NAME"
    }
    starts = {s for s, _ in name_spans}
    assert len(starts) >= 2, f"expected title-boundary disagreement, got {name_spans}"


def test_soft_labels_carry_fractional_boundary_mass():
    docs = generate_corpus(40, seed=13)
    fractional = 0
    for doc in docs:
        offsets = _whitespace_offsets(doc.text)
        for row in soft_labels(doc.text, offsets):
            for label_id, p in enumerate(row):
                if label_id != O_ID and 0.0 < p < 1.0:
                    fractional += 1
    assert fractional > 50, "soft labels look degenerate (no boundary uncertainty)"


def test_ensemble_union_recall_on_gold_spans():
    """The teacher must be a decent teacher: the union of the 5 annotators
    should overlap the vast majority of gold PHI spans."""
    docs = generate_corpus(80, seed=7)
    total, hit = 0, 0
    for doc in docs:
        union = [s for spans in annotate_ensemble(doc.text) for s in spans]
        for gold in doc.spans:
            total += 1
            if any(
                s < gold.end and gold.start < e and label == gold.label
                for (s, e, label) in union
            ):
                hit += 1
    recall = hit / total
    assert recall >= 0.90, f"teacher union recall {recall:.3f} ({hit}/{total})"


def test_hard_negatives_stay_mostly_clean():
    docs = [d for d in generate_corpus(200, seed=3) if set(d.families) == {"hard_negative"}]
    assert docs
    votes = 0
    tokens = 0
    for doc in docs:
        offsets = _whitespace_offsets(doc.text)
        for row in soft_labels(doc.text, offsets):
            tokens += 1
            votes += 1.0 - row[O_ID]
    assert votes / tokens < 0.05, f"teachers hallucinate PHI on {votes / tokens:.1%} of clean tokens"


def test_spans_to_bio_marks_b_then_i():
    text = "call Sarah Johnson today"
    offsets = _whitespace_offsets(text)
    labels = spans_to_bio_ids([(5, 18, "NAME")], offsets)
    assert labels == [
        O_ID, LABEL_TO_ID["B-NAME"], LABEL_TO_ID["I-NAME"], O_ID,
    ]


def test_soft_labels_rows_sum_to_one():
    text = "referral received march 3, 2024 for Sarah Johnson (mrn 1234567)."
    offsets = _whitespace_offsets(text)
    for row in soft_labels(text, offsets):
        assert abs(sum(row) - 1.0) < 1e-9
        assert all(p in {0.0, 0.2, 0.4, 0.6, 0.8, 1.0} for p in row)  # K=5 votes
    assert K == 5
