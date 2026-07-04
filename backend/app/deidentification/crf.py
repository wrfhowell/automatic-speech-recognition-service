"""Linear-chain CRF with learned transitions and BIO structural constraints.

Constraints are additive penalties of -1e4 — never -inf — so the
forward-algorithm logsumexp can't produce NaN when every path through a
label is disallowed (the paper's trick; -inf minus -inf poisons gradients).
"""

import torch
from torch import Tensor, nn

from app.deid.labels import NUM_LABELS, allowed_starts, allowed_transitions

CONSTRAINT_PENALTY = -1e4


def _transition_penalty() -> Tensor:
    allowed = torch.tensor(allowed_transitions(), dtype=torch.bool)
    return torch.where(allowed, 0.0, CONSTRAINT_PENALTY)


def _start_penalty() -> Tensor:
    allowed = torch.tensor(allowed_starts(), dtype=torch.bool)
    return torch.where(allowed, 0.0, CONSTRAINT_PENALTY)


class CRF(nn.Module):
    def __init__(self, num_labels: int = NUM_LABELS) -> None:
        super().__init__()
        self.num_labels = num_labels
        self.transitions = nn.Parameter(torch.zeros(num_labels, num_labels))
        self.start_transitions = nn.Parameter(torch.zeros(num_labels))
        self.end_transitions = nn.Parameter(torch.zeros(num_labels))
        if num_labels == NUM_LABELS:
            self.register_buffer("transition_penalty", _transition_penalty())
            self.register_buffer("start_penalty", _start_penalty())
        else:  # tiny label spaces in tests
            self.register_buffer("transition_penalty", torch.zeros(num_labels, num_labels))
            self.register_buffer("start_penalty", torch.zeros(num_labels))

    def constrained_transitions(self) -> Tensor:
        return self.transitions + self.transition_penalty

    def constrained_starts(self) -> Tensor:
        return self.start_transitions + self.start_penalty

    def nll(self, emissions: Tensor, tags: Tensor, mask: Tensor) -> Tensor:
        """Mean negative log-likelihood: logZ (forward algorithm) minus the
        score of the tag path. emissions [B,T,L], tags [B,T], mask [B,T]."""
        mask = mask.bool()
        log_z = self._forward_logz(emissions, mask)
        path = self._path_score(emissions, tags, mask)
        return (log_z - path).mean()

    def _path_score(self, emissions: Tensor, tags: Tensor, mask: Tensor) -> Tensor:
        batch, seq_len, _ = emissions.shape
        trans = self.constrained_transitions()
        score = self.constrained_starts()[tags[:, 0]] + emissions[:, 0].gather(
            1, tags[:, 0:1]
        ).squeeze(1)
        for t in range(1, seq_len):
            step = (
                trans[tags[:, t - 1], tags[:, t]]
                + emissions[:, t].gather(1, tags[:, t : t + 1]).squeeze(1)
            )
            score = score + step * mask[:, t]
        last_idx = mask.long().sum(dim=1) - 1
        last_tags = tags.gather(1, last_idx.unsqueeze(1)).squeeze(1)
        return score + self.end_transitions[last_tags]

    def _forward_logz(self, emissions: Tensor, mask: Tensor) -> Tensor:
        _, seq_len, _ = emissions.shape
        trans = self.constrained_transitions()  # [L, L]
        alpha = self.constrained_starts() + emissions[:, 0]  # [B, L]
        for t in range(1, seq_len):
            # [B, L_from, 1] + [L_from, L_to] + [B, 1, L_to]
            inner = alpha.unsqueeze(2) + trans + emissions[:, t].unsqueeze(1)
            next_alpha = torch.logsumexp(inner, dim=1)
            keep = mask[:, t].unsqueeze(1)
            alpha = torch.where(keep, next_alpha, alpha)
        return torch.logsumexp(alpha + self.end_transitions, dim=1)
