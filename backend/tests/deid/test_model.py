"""DeidStudent: forward shape, constrained decode, save/load round-trip.

Uses a tiny randomly-initialized BERT config — no network, no hub weights.
"""

import torch
from transformers import BertConfig, BertModel

from app.deidentification.labels import LABELS, NUM_LABELS
from app.deidentification.model import DeidStudent, load_student, save_student

_TINY = BertConfig(
    vocab_size=100,
    hidden_size=32,
    num_hidden_layers=1,
    num_attention_heads=2,
    intermediate_size=64,
    max_position_embeddings=64,
)


def _tiny_student() -> DeidStudent:
    torch.manual_seed(0)
    return DeidStudent(BertModel(_TINY))


def test_forward_emissions_shape():
    model = _tiny_student()
    input_ids = torch.randint(0, 100, (3, 10))
    mask = torch.ones(3, 10, dtype=torch.long)
    emissions = model(input_ids, mask)
    assert emissions.shape == (3, 10, NUM_LABELS)


def test_decode_respects_mask_lengths_and_bio_constraints():
    model = _tiny_student().eval()
    input_ids = torch.randint(0, 100, (2, 12))
    mask = torch.ones(2, 12, dtype=torch.long)
    mask[1, 7:] = 0
    emissions = model(input_ids, mask)
    paths = model.decode(emissions, mask)
    assert [len(p) for p in paths] == [12, 7]
    for path in paths:
        assert not LABELS[path[0]].startswith("I-")  # I-X can't start
        for prev, cur in zip(path, path[1:]):
            if LABELS[cur].startswith("I-"):
                entity = LABELS[cur].split("-", 1)[1]
                assert LABELS[prev] in (f"B-{entity}", f"I-{entity}")


def test_save_load_round_trip(tmp_path):
    model = _tiny_student().eval()
    save_student(model, tmp_path)
    loaded = load_student(tmp_path)
    assert not loaded.training  # load_student returns eval-mode model

    input_ids = torch.randint(0, 100, (2, 8))
    mask = torch.ones(2, 8, dtype=torch.long)
    with torch.no_grad():
        original = model(input_ids, mask)
        restored = loaded(input_ids, mask)
    assert torch.allclose(original, restored)
