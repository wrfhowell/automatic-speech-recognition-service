from app.deidentification import PhiSpan
from app.deidentification.masking import apply_masks, bio_to_spans, merge_spans

# "jane smith called from boston"
#  0123456789012345678901234567890
TEXT = "jane smith called from boston"
TOKENS = [
    ("jane", (0, 4)),
    ("smith", (5, 10)),
    ("called", (11, 17)),
    ("from", (18, 22)),
    ("boston", (23, 29)),
]
OFFSETS = [o for _, o in TOKENS]


def test_b_i_sequence_becomes_one_span():
    labels = ["B-NAME", "I-NAME", "O", "O", "B-LOC"]
    spans = bio_to_spans(labels, OFFSETS)
    assert spans == [PhiSpan(0, 10, "NAME"), PhiSpan(23, 29, "LOC")]
    assert TEXT[0:10] == "jane smith"


def test_orphan_i_opens_a_span():
    # Recall-first: I-NAME with nothing open must still mask.
    labels = ["O", "I-NAME", "O", "O", "O"]
    assert bio_to_spans(labels, OFFSETS) == [PhiSpan(5, 10, "NAME")]


def test_i_with_mismatched_type_opens_new_span():
    labels = ["B-NAME", "I-DATE", "O", "O", "O"]
    assert bio_to_spans(labels, OFFSETS) == [
        PhiSpan(0, 4, "NAME"),
        PhiSpan(5, 10, "DATE"),
    ]


def test_b_after_b_closes_previous():
    labels = ["B-NAME", "B-NAME", "O", "O", "O"]
    assert bio_to_spans(labels, OFFSETS) == [
        PhiSpan(0, 4, "NAME"),
        PhiSpan(5, 10, "NAME"),
    ]


def test_special_tokens_with_zero_offsets_are_skipped():
    labels = ["O", "B-NAME", "I-NAME", "O", "O", "O", "O"]
    offsets = [(0, 0)] + OFFSETS + [(0, 0)]
    assert bio_to_spans(labels, offsets) == [PhiSpan(0, 10, "NAME")]


def test_base_offset_shifts_spans():
    labels = ["B-NAME", "I-NAME", "O", "O", "O"]
    spans = bio_to_spans(labels, OFFSETS, base_offset=100)
    assert spans == [PhiSpan(100, 110, "NAME")]


def test_merge_spans_joins_whitespace_separated_same_label():
    spans = [PhiSpan(0, 4, "NAME"), PhiSpan(5, 10, "NAME")]
    assert merge_spans(spans, TEXT) == [PhiSpan(0, 10, "NAME")]


def test_merge_spans_keeps_different_labels_apart():
    spans = [PhiSpan(0, 10, "NAME"), PhiSpan(23, 29, "LOC")]
    assert merge_spans(spans, TEXT) == spans


def test_merge_spans_clamps_overlap():
    spans = [PhiSpan(0, 10, "NAME"), PhiSpan(5, 17, "DATE")]
    assert merge_spans(spans, TEXT) == [PhiSpan(0, 10, "NAME"), PhiSpan(10, 17, "DATE")]


def test_apply_masks_rebuilds_from_slices():
    spans = [PhiSpan(0, 10, "NAME"), PhiSpan(23, 29, "LOC")]
    assert apply_masks(TEXT, spans) == "[NAME] called from [LOC]"


def test_apply_masks_no_spans_is_identity():
    assert apply_masks(TEXT, []) == TEXT
