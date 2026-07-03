"""Vectorized batched Viterbi decode (the paper's 20-50x speedup over
per-sequence decoding): one Python loop over T of pure tensor ops,
preallocated backpointers, and a single .cpu() sync at the end."""

import itertools

import torch
from torch import Tensor


@torch.no_grad()
def viterbi_decode(
    emissions: Tensor,          # [B, T, L]
    mask: Tensor,               # [B, T] bool
    transitions: Tensor,        # [L, L] (constraints already added)
    start_transitions: Tensor,  # [L]
    end_transitions: Tensor,    # [L]
) -> list[list[int]]:
    batch, seq_len, num_labels = emissions.shape
    mask = mask.bool()

    score = start_transitions + emissions[:, 0]  # [B, L]
    backpointers = torch.empty(batch, seq_len, num_labels, dtype=torch.long)
    backpointers[:, 0] = 0
    identity = torch.arange(num_labels)

    for t in range(1, seq_len):
        # [B, L_from, 1] + [L_from, L_to] + [B, 1, L_to] -> [B, L_from, L_to]
        candidate = score.unsqueeze(2) + transitions + emissions[:, t].unsqueeze(1)
        best_score, best_from = candidate.max(dim=1)  # [B, L]
        keep = mask[:, t].unsqueeze(1)
        # Padded steps carry score forward with identity backpointers, so the
        # end bonus applied at T-1 lands on each sequence's true last token.
        score = torch.where(keep, best_score, score)
        backpointers[:, t] = torch.where(keep, best_from, identity)

    last_label = (score + end_transitions).argmax(dim=1)  # [B]

    # Single device->host transfer, then pure-python backtrace.
    bp = backpointers.cpu().tolist()
    lengths = mask.sum(dim=1).cpu().tolist()
    last = last_label.cpu().tolist()

    paths: list[list[int]] = []
    for b in range(batch):
        label = last[b]
        path = [label]
        for t in range(seq_len - 1, 0, -1):
            label = bp[b][t][label]
            path.append(label)
        path.reverse()
        paths.append(path[: lengths[b]])
    return paths


def brute_force_decode(
    emissions: Tensor,
    mask: Tensor,
    transitions: Tensor,
    start_transitions: Tensor,
    end_transitions: Tensor,
) -> list[list[int]]:
    """Exhaustive argmax over all label sequences. Tiny inputs only; exists
    to pin viterbi_decode's correctness."""
    batch, _, num_labels = emissions.shape
    results = []
    for b in range(batch):
        length = int(mask[b].sum().item())
        best_score, best_path = None, None
        for path in itertools.product(range(num_labels), repeat=length):
            score = start_transitions[path[0]] + emissions[b, 0, path[0]]
            for t in range(1, length):
                score = score + transitions[path[t - 1], path[t]] + emissions[b, t, path[t]]
            score = score + end_transitions[path[-1]]
            if best_score is None or score.item() > best_score:
                best_score, best_path = score.item(), list(path)
        results.append(best_path)
    return results
