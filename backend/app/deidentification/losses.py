"""CIPHER training losses.

Focal soft cross-entropy (paper eq., γ=2):
    ℒ = −(1/Σmask) Σ_t (1−p̂_t)^γ Σ_ℓ p_t(ℓ) log q_t(ℓ)
where p_t is the teacher ensemble's soft vote distribution, q_t the
student's softmax, and p̂_t the student's probability of the teacher's
argmax label. The focal weight is detached: it scales the gradient of
hard tokens up but is not itself differentiated — the ocean of easy "O"
tokens must not drown the gradient.

Combined: ℒ = α·ℒ_distill + (1−α)·ℒ_CRF with the CRF NLL taken on the
teacher argmax labels (the paper's biggest ablation win is soft labels
in the distill term, +3.45 F1 vs hard).
"""

from dataclasses import dataclass

import torch
from torch import Tensor
from torch.nn.functional import log_softmax, softmax

from app.deidentification.crf import CRF


def focal_soft_cross_entropy(
    logits: Tensor,  # [B, T, L]
    soft_targets: Tensor,  # [B, T, L], rows sum to 1
    mask: Tensor,  # [B, T]
    gamma: float = 2.0,
) -> Tensor:
    mask = mask.to(logits.dtype)
    log_q = log_softmax(logits, dim=-1)
    q = softmax(logits, dim=-1)

    teacher_argmax = soft_targets.argmax(dim=-1, keepdim=True)  # [B, T, 1]
    p_hat = q.gather(-1, teacher_argmax).squeeze(-1)  # [B, T]
    focal_weight = (1.0 - p_hat).detach() ** gamma

    ce = -(soft_targets * log_q).sum(dim=-1)  # [B, T]
    return (focal_weight * ce * mask).sum() / mask.sum().clamp(min=1)


@dataclass
class LossParts:
    total: Tensor
    distill: Tensor
    crf_nll: Tensor | None


def combined_loss(
    logits: Tensor,
    soft_targets: Tensor,
    mask: Tensor,
    crf: CRF,
    *,
    alpha: float = 0.5,
    gamma: float = 2.0,
    use_crf: bool = True,
) -> LossParts:
    distill = focal_soft_cross_entropy(logits, soft_targets, mask, gamma=gamma)
    if not use_crf:
        return LossParts(total=distill, distill=distill, crf_nll=None)
    crf_nll = crf.nll(logits, soft_targets.argmax(dim=-1), mask)
    return LossParts(
        total=alpha * distill + (1.0 - alpha) * crf_nll,
        distill=distill,
        crf_nll=crf_nll,
    )


def harden(soft_targets: Tensor) -> Tensor:
    """--hard-labels ablation: one-hot of the teacher argmax."""
    return torch.zeros_like(soft_targets).scatter_(
        -1, soft_targets.argmax(dim=-1, keepdim=True), 1.0
    )
