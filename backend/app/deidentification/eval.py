"""Span-level evaluation on the entity-dense eval set.

Recall is what matters (§11): a gold span counts as recalled only if every
non-whitespace character of it is covered by SOME predicted span — the
label may be wrong, but the characters must be masked. Anything less is a
PHI leak. masked_char_precision (predicted-span chars that fall inside
gold spans) is reported as the over-masking indicator.

python -m app.deidentification.eval re-runs the committed artifacts against a freshly
regenerated dense eval set and prints metrics.json-shaped output.
"""

import json
from collections.abc import Callable

from app.deidentification import PhiSpan
from app.deidentification.data.generate import Document
from app.deidentification.labels import PHI_TYPES

SYNTHETIC_CAVEAT = (
    "Evaluated on synthetic, in-distribution data only. The CIPHER paper "
    "reports a ~19-point F1 drop moving from synthetic evaluation to real "
    "clinical text; treat these numbers as an upper bound that certifies "
    "the pipeline, not as clinical-grade performance."
)

RECALL_GATE_OVERALL = 0.90
RECALL_GATE_PER_TYPE = 0.85


def span_recalled(text: str, start: int, end: int, predicted: list[PhiSpan]) -> bool:
    """Every non-whitespace char of [start, end) lies inside a predicted span."""
    for i in range(start, end):
        if text[i].isspace():
            continue
        if not any(s.start <= i < s.end for s in predicted):
            return False
    return True


def evaluate(predict: Callable[[str], list[PhiSpan]], docs: list[Document]) -> dict:
    recalled = {t: 0 for t in PHI_TYPES}
    total = {t: 0 for t in PHI_TYPES}
    pred_chars = 0
    pred_chars_in_gold = 0

    for doc in docs:
        predicted = predict(doc.text)
        for gold in doc.spans:
            total[gold.label] += 1
            if span_recalled(doc.text, gold.start, gold.end, predicted):
                recalled[gold.label] += 1
        gold_intervals = [(g.start, g.end) for g in doc.spans]
        for span in predicted:
            pred_chars += span.end - span.start
            pred_chars_in_gold += sum(
                max(0, min(span.end, ge) - max(span.start, gs))
                for gs, ge in gold_intervals
            )

    n_gold = sum(total.values())
    per_type = {t: (recalled[t] / total[t] if total[t] else None) for t in PHI_TYPES}
    return {
        "overall_recall": sum(recalled.values()) / n_gold if n_gold else None,
        "per_type_recall": per_type,
        "masked_char_precision": (
            pred_chars_in_gold / pred_chars if pred_chars else None
        ),
        "n_docs": len(docs),
        "n_gold_spans": n_gold,
        "gold_spans_per_type": total,
    }


def passes_gate(metrics: dict) -> bool:
    if (metrics["overall_recall"] or 0) < RECALL_GATE_OVERALL:
        return False
    return all(
        (r or 0) >= RECALL_GATE_PER_TYPE for r in metrics["per_type_recall"].values()
    )


def main() -> None:
    from app.deidentification.data.generate import generate_dense_eval
    from app.deidentification.inference import Deidentifier
    from app.deidentification.model import ARTIFACTS_DIR

    config = json.loads((ARTIFACTS_DIR / "config.json").read_text())
    docs = generate_dense_eval(config["n_eval_dense"], seed=config["seed_eval"])
    deid = Deidentifier.from_artifacts()
    metrics = evaluate(deid.predict_spans, docs)
    metrics["caveat"] = SYNTHETIC_CAVEAT
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
