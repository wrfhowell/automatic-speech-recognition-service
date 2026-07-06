import re

from app.deidentification.data.features import (
    N_FEATURES,
    doc_features,
    is_outlier,
    robust_z_scores,
    sample_training_set,
)
from app.deidentification.data.generate import generate_corpus, generate_dense_eval
from app.deidentification.labels import PHI_TYPES


def test_spans_are_correct_by_construction():
    # The core property: every recorded span slices to its surface text.
    for doc in generate_corpus(200, seed=13):
        for span in doc.spans:
            assert doc.text[span.start : span.end] == span.text
            assert span.label in PHI_TYPES


def test_generation_is_deterministic():
    a = generate_corpus(20, seed=13)
    b = generate_corpus(20, seed=13)
    assert [d.text for d in a] == [d.text for d in b]


def test_no_unfilled_slots_remain():
    for doc in generate_corpus(100, seed=7):
        assert not re.search(r"\{(name|first|date|phone|mrn|loc|age)\d*\}", doc.text)


def test_corpus_mixes_families_and_includes_hard_negatives():
    docs = generate_corpus(300, seed=13)
    families = {f for d in docs for f in d.families}
    assert families == {"dialogue", "intake", "narrative", "hard_negative"}
    pure_negative = [d for d in docs if set(d.families) == {"hard_negative"}]
    assert pure_negative, "some documents should be entirely PHI-free"
    assert all(d.spans == [] for d in pure_negative)


def test_dense_eval_has_min_instances_per_type():
    docs = generate_dense_eval(150, seed=99, min_per_type=40)
    counts = {t: 0 for t in PHI_TYPES}
    for doc in docs:
        for span in doc.spans:
            counts[span.label] += 1
    assert all(c >= 40 for c in counts.values()), counts


def test_features_shape_and_finiteness():
    docs = generate_corpus(50, seed=3)
    matrix = [doc_features(d) for d in docs]
    assert all(len(row) == N_FEATURES for row in matrix)
    zs = robust_z_scores(matrix)
    assert all(all(abs(z) < 1e6 for z in row) for row in zs)


def test_sampling_returns_exact_n_with_outliers_included():
    candidates = generate_corpus(600, seed=13)
    picked = sample_training_set(candidates, n=400, seed=13)
    assert len(picked) == 400
    assert len({id(d) for d in picked}) == 400  # no duplicates

    zs = robust_z_scores([doc_features(d) for d in candidates])
    outlier_ids = {id(d) for d, z in zip(candidates, zs) if is_outlier(z)}
    n_outliers_picked = sum(1 for d in picked if id(d) in outlier_ids)
    assert n_outliers_picked > 0, "outlier oversampling had no effect"
