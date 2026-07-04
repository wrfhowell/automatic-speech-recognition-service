"""Outlier-aware training-set sampling (paper §outlier-aware sampling):
14 lexical features per document, robust Z-scores via MAD, then 90%
family-stratified inliers + 10% outlier oversample."""

import random
import re
import statistics

from app.deid.data.generate import Document

N_FEATURES = 14

_PUNCT_RE = re.compile(r"[^\w\s]")
_DIGIT_RE = re.compile(r"\d")
_UPPER_RE = re.compile(r"[A-Z]")
_SENT_SPLIT = re.compile(r"[.!?\n]+")


def doc_features(doc: Document) -> list[float]:
    text = doc.text
    n_chars = max(len(text), 1)
    tokens = text.split()
    n_tokens = max(len(tokens), 1)
    sentences = [s for s in _SENT_SPLIT.split(text) if s.strip()]
    phi_chars = sum(s.end - s.start for s in doc.spans)
    return [
        float(len(text)),
        float(len(tokens)),
        sum(len(t) for t in tokens) / n_tokens,
        len(_DIGIT_RE.findall(text)) / n_chars,
        len(_PUNCT_RE.findall(text)) / n_chars,
        len(_UPPER_RE.findall(text)) / n_chars,
        text.count("\n") / n_chars,
        sum(1 for t in tokens if any(c.isdigit() for c in t)) / n_tokens,
        float(len(doc.spans)),
        phi_chars / n_chars,
        float(len({s.label for s in doc.spans})),
        float(max((s.end - s.start for s in doc.spans), default=0)),
        (n_tokens / max(len(sentences), 1)),
        text.count(":") / n_chars,
    ]


def robust_z_scores(matrix: list[list[float]]) -> list[list[float]]:
    """Per-feature robust Z: (x - median) / (1.4826 * MAD); 0 where MAD=0."""
    n_docs = len(matrix)
    zs = [[0.0] * N_FEATURES for _ in range(n_docs)]
    for j in range(N_FEATURES):
        column = [row[j] for row in matrix]
        med = statistics.median(column)
        mad = statistics.median(abs(x - med) for x in column)
        scale = 1.4826 * mad
        if scale == 0:
            continue
        for i in range(n_docs):
            zs[i][j] = (column[i] - med) / scale
    return zs


def is_outlier(z_row: list[float], threshold: float = 2.0) -> bool:
    return max(abs(z) for z in z_row) > threshold


def sample_training_set(
    candidates: list[Document], n: int, seed: int, outlier_fraction: float = 0.10
) -> list[Document]:
    rng = random.Random(seed)
    zs = robust_z_scores([doc_features(d) for d in candidates])
    outliers = [d for d, z in zip(candidates, zs) if is_outlier(z)]
    inliers = [d for d, z in zip(candidates, zs) if not is_outlier(z)]

    n_outliers = min(len(outliers), int(n * outlier_fraction))
    picked = rng.sample(outliers, n_outliers)

    # Stratify the inlier draw by primary template family.
    n_inliers = n - n_outliers
    by_family: dict[str, list[Document]] = {}
    for doc in inliers:
        by_family.setdefault(doc.primary_family, []).append(doc)
    total = len(inliers)
    for family, docs in sorted(by_family.items()):
        share = round(n_inliers * len(docs) / total)
        picked.extend(rng.sample(docs, min(share, len(docs))))
    # Rounding drift (and small inlier pools) top up from anything unpicked.
    picked_ids = {id(d) for d in picked}
    remaining = [d for d in candidates if id(d) not in picked_ids]
    rng.shuffle(remaining)
    while len(picked) < n and remaining:
        picked.append(remaining.pop())
    rng.shuffle(picked)
    return picked[:n]
