import torch

from app.deid.crf import CONSTRAINT_PENALTY, CRF
from app.deid.labels import LABEL_TO_ID, NUM_LABELS
from app.deid.viterbi import brute_force_decode, viterbi_decode


def _decode_with(crf: CRF, emissions, mask):
    return viterbi_decode(
        emissions, mask,
        crf.constrained_transitions(), crf.constrained_starts(), crf.end_transitions,
    )


def test_viterbi_matches_brute_force_on_random_inputs():
    torch.manual_seed(13)
    for _ in range(20):
        batch, seq_len, labels = 3, 4, 5
        emissions = torch.randn(batch, seq_len, labels)
        transitions = torch.randn(labels, labels)
        start = torch.randn(labels)
        end = torch.randn(labels)
        mask = torch.ones(batch, seq_len, dtype=torch.bool)
        fast = viterbi_decode(emissions, mask, transitions, start, end)
        slow = brute_force_decode(emissions, mask, transitions, start, end)
        assert fast == slow


def test_viterbi_matches_brute_force_with_variable_lengths():
    torch.manual_seed(7)
    for _ in range(10):
        emissions = torch.randn(3, 5, 4)
        transitions = torch.randn(4, 4)
        start, end = torch.randn(4), torch.randn(4)
        mask = torch.tensor(
            [[1, 1, 1, 1, 1], [1, 1, 1, 0, 0], [1, 0, 0, 0, 0]], dtype=torch.bool
        )
        fast = viterbi_decode(emissions, mask, transitions, start, end)
        slow = brute_force_decode(emissions, mask, transitions, start, end)
        assert fast == slow
        assert [len(p) for p in fast] == [5, 3, 1]


def test_constrained_decode_never_emits_illegal_bio():
    torch.manual_seed(13)
    crf = CRF()
    # Emissions that scream I-NAME everywhere; constraints must forbid
    # starting with it or entering it from a non-NAME label.
    emissions = torch.full((2, 6, NUM_LABELS), -1.0)
    emissions[:, :, LABEL_TO_ID["I-NAME"]] = 5.0
    emissions[:, 3, LABEL_TO_ID["B-DATE"]] = 10.0  # force a break mid-sequence
    mask = torch.ones(2, 6, dtype=torch.bool)
    paths = _decode_with(crf, emissions, mask)
    for path in paths:
        prev = None
        for label_id in path:
            label = list(LABEL_TO_ID)[label_id]
            if label.startswith("I-"):
                entity = label[2:]
                assert prev is not None and prev in (f"B-{entity}", f"I-{entity}"), (
                    f"illegal {label} after {prev}: {paths}"
                )
            prev = label
    # The high-emission I-NAME region must have been realized as B-NAME -> I-NAME...
    assert LABEL_TO_ID["B-NAME"] in paths[0]


def test_crf_nll_finite_even_when_gold_path_is_illegal():
    # Teacher argmax labels can be structurally illegal; -1e4 (not -inf)
    # keeps the loss finite and gradients clean.
    crf = CRF()
    emissions = torch.randn(2, 4, NUM_LABELS, requires_grad=True)
    illegal = torch.full((2, 4), LABEL_TO_ID["I-NAME"], dtype=torch.long)
    mask = torch.ones(2, 4, dtype=torch.bool)
    loss = crf.nll(emissions, illegal, mask)
    assert torch.isfinite(loss)
    loss.backward()
    assert torch.isfinite(emissions.grad).all()
    assert abs(loss.item()) < abs(CONSTRAINT_PENALTY) * 10  # sane magnitude


def test_crf_nll_decreases_for_likelier_paths():
    torch.manual_seed(13)
    crf = CRF(num_labels=3)
    emissions = torch.zeros(1, 4, 3)
    emissions[0, :, 1] = 3.0  # label 1 strongly favored everywhere
    mask = torch.ones(1, 4, dtype=torch.bool)
    good = torch.full((1, 4), 1, dtype=torch.long)
    bad = torch.full((1, 4), 2, dtype=torch.long)
    assert crf.nll(emissions, good, mask) < crf.nll(emissions, bad, mask)


def test_crf_nll_is_a_proper_distribution():
    # exp(-nll) summed over all paths == 1 for a tiny space.
    torch.manual_seed(3)
    crf = CRF(num_labels=2)
    emissions = torch.randn(1, 3, 2)
    mask = torch.ones(1, 3, dtype=torch.bool)
    import itertools

    total = 0.0
    for path in itertools.product(range(2), repeat=3):
        tags = torch.tensor([path])
        total += torch.exp(-crf.nll(emissions, tags, mask)).item()
    assert abs(total - 1.0) < 1e-4
