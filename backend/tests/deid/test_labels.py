from app.deid.labels import (
    LABEL_TO_ID,
    LABELS,
    NUM_LABELS,
    allowed_starts,
    allowed_transitions,
    mask_token,
)


def test_label_space_is_13():
    assert NUM_LABELS == 13
    assert LABELS[0] == "O"
    assert "B-NAME" in LABELS and "I-AGE" in LABELS


def test_mask_tokens():
    assert mask_token("NAME") == "[NAME]"
    assert mask_token("MRN") == "[MRN]"


def test_i_only_follows_same_entity():
    allowed = allowed_transitions()
    assert allowed[LABEL_TO_ID["B-NAME"]][LABEL_TO_ID["I-NAME"]]
    assert allowed[LABEL_TO_ID["I-NAME"]][LABEL_TO_ID["I-NAME"]]
    assert not allowed[LABEL_TO_ID["B-DATE"]][LABEL_TO_ID["I-NAME"]]
    assert not allowed[LABEL_TO_ID["O"]][LABEL_TO_ID["I-PHONE"]]


def test_b_and_o_always_reachable():
    allowed = allowed_transitions()
    for i in range(NUM_LABELS):
        assert allowed[i][LABEL_TO_ID["O"]]
        assert allowed[i][LABEL_TO_ID["B-LOC"]]


def test_i_cannot_start():
    starts = allowed_starts()
    assert starts[LABEL_TO_ID["O"]]
    assert starts[LABEL_TO_ID["B-NAME"]]
    assert not starts[LABEL_TO_ID["I-NAME"]]
    assert not starts[LABEL_TO_ID["I-AGE"]]
