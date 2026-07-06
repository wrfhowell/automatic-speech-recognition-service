import math

import torch

from app.deidentification.crf import CRF
from app.deidentification.losses import combined_loss, focal_soft_cross_entropy, harden


def test_focal_loss_matches_hand_computed_value():
    # Single token, 2 labels. logits (0, ln3) -> q = (0.25, 0.75).
    logits = torch.tensor([[[0.0, math.log(3.0)]]])
    soft = torch.tensor([[[0.4, 0.6]]])  # teacher argmax = label 1
    mask = torch.ones(1, 1)
    # p_hat = 0.75; weight = (1-0.75)^2 = 0.0625
    # ce = -(0.4*ln0.25 + 0.6*ln0.75)
    ce = -(0.4 * math.log(0.25) + 0.6 * math.log(0.75))
    expected = 0.0625 * ce
    got = focal_soft_cross_entropy(logits, soft, mask, gamma=2.0).item()
    assert abs(got - expected) < 1e-6


def test_gamma_zero_reduces_to_plain_soft_ce():
    torch.manual_seed(13)
    logits = torch.randn(2, 3, 5)
    soft = torch.softmax(torch.randn(2, 3, 5), dim=-1)
    mask = torch.ones(2, 3)
    got = focal_soft_cross_entropy(logits, soft, mask, gamma=0.0)
    expected = (-(soft * torch.log_softmax(logits, -1)).sum(-1)).mean()
    assert torch.allclose(got, expected, atol=1e-6)


def test_confident_correct_tokens_are_downweighted():
    # Student very confident and right -> tiny focal loss; uncertain -> larger.
    soft = torch.tensor([[[0.0, 1.0]]])
    mask = torch.ones(1, 1)
    confident = torch.tensor([[[0.0, 10.0]]])
    uncertain = torch.tensor([[[0.0, 0.1]]])
    l_conf = focal_soft_cross_entropy(confident, soft, mask).item()
    l_unc = focal_soft_cross_entropy(uncertain, soft, mask).item()
    assert l_conf < l_unc / 100


def test_focal_weight_is_detached_from_the_graph():
    logits = torch.tensor([[[1.0, 2.0]]], requires_grad=True)
    soft = torch.tensor([[[0.3, 0.7]]])
    mask = torch.ones(1, 1)
    loss = focal_soft_cross_entropy(logits, soft, mask)
    loss.backward()
    # Gradient equals focal_weight * d(ce)/d(logits): weight w = (1-q1)^2.
    q = torch.softmax(torch.tensor([1.0, 2.0]), 0)
    w = (1 - q[1]) ** 2
    expected_grad = w * (q - torch.tensor([0.3, 0.7]))
    assert torch.allclose(logits.grad.squeeze(), expected_grad, atol=1e-5)


def test_masked_tokens_contribute_nothing():
    torch.manual_seed(3)
    logits = torch.randn(1, 4, 5)
    soft = torch.softmax(torch.randn(1, 4, 5), -1)
    full = focal_soft_cross_entropy(logits, soft, torch.tensor([[1.0, 1.0, 0.0, 0.0]]))
    trunc = focal_soft_cross_entropy(logits[:, :2], soft[:, :2], torch.ones(1, 2))
    assert torch.allclose(full, trunc, atol=1e-6)


def test_combined_loss_blends_alpha():
    torch.manual_seed(13)
    crf = CRF(num_labels=5)
    logits = torch.randn(2, 3, 5)
    soft = torch.softmax(torch.randn(2, 3, 5), -1)
    mask = torch.ones(2, 3)
    parts = combined_loss(logits, soft, mask, crf, alpha=0.5)
    assert torch.allclose(
        parts.total, 0.5 * parts.distill + 0.5 * parts.crf_nll, atol=1e-6
    )
    no_crf = combined_loss(logits, soft, mask, crf, use_crf=False)
    assert no_crf.crf_nll is None
    assert torch.allclose(no_crf.total, no_crf.distill)


def test_harden_produces_one_hot_argmax():
    soft = torch.tensor([[[0.2, 0.5, 0.3], [0.6, 0.3, 0.1]]])
    hard = harden(soft)
    assert hard.tolist() == [[[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]]
