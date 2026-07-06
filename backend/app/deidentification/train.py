"""python -m app.deidentification.train — distill the teacher ensemble into the student.

Pipeline: 2,500 candidate docs -> outlier-aware sample of 2,000 train
(+300 val, +150 entity-dense eval), teacher soft labels per wordpiece,
AdamW (head/CRF 5e-4, encoder 1e-4), 4 epochs, batch 32, seed 13 —
minutes on CPU.

Main run commits artifacts/ (student.pt, encoder_config.json, tokenizer/,
config.json, labels.json, metrics.json, data/*.jsonl). Ablation flags
(--hard-labels, --gamma, --no-crf-loss) write metrics_<slug>.json ONLY —
they never clobber the shipped weights.
"""

import argparse
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

import torch
from transformers import AutoTokenizer, PreTrainedTokenizerFast

from app.deidentification.data.features import sample_training_set
from app.deidentification.data.generate import (
    Document,
    generate_corpus,
    generate_dense_eval,
)
from app.deidentification.eval import SYNTHETIC_CAVEAT, evaluate, passes_gate
from app.deidentification.labels import LABELS, NUM_LABELS, O_ID
from app.deidentification.losses import combined_loss, harden
from app.deidentification.model import (
    ARTIFACTS_DIR,
    ENCODER_NAME,
    TOKENIZER_NAME,
    pretrained_student,
    save_student,
)
from app.deidentification.teacher import soft_labels

MAX_LENGTH = 384  # docs are 2-5 short templates; bert-tiny caps at 512

SEED_TRAIN = 13
SEED_VAL = 14
SEED_EVAL = 15
N_CANDIDATES = 2500
N_TRAIN = 2000
N_VAL = 300
N_EVAL_DENSE = 150


@dataclass
class Example:
    input_ids: torch.Tensor  # [T]
    soft: torch.Tensor  # [T, NUM_LABELS]


def encode_docs(
    docs: list[Document], tokenizer: PreTrainedTokenizerFast
) -> list[Example]:
    examples = []
    for doc in docs:
        enc = tokenizer(
            doc.text,
            truncation=True,
            max_length=MAX_LENGTH,
            return_offsets_mapping=True,
        )
        soft = soft_labels(doc.text, enc["offset_mapping"])
        examples.append(
            Example(
                input_ids=torch.tensor(enc["input_ids"], dtype=torch.long),
                soft=torch.tensor(soft, dtype=torch.float),
            )
        )
    return examples


def collate(
    batch: list[Example], pad_id: int
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    max_len = max(len(ex.input_ids) for ex in batch)
    input_ids = torch.full((len(batch), max_len), pad_id, dtype=torch.long)
    mask = torch.zeros(len(batch), max_len, dtype=torch.long)
    soft = torch.zeros(len(batch), max_len, NUM_LABELS)
    soft[:, :, O_ID] = 1.0  # padding rows: O one-hot (masked out of every loss)
    for i, ex in enumerate(batch):
        n = len(ex.input_ids)
        input_ids[i, :n] = ex.input_ids
        mask[i, :n] = 1
        soft[i, :n] = ex.soft
    return input_ids, mask, soft


def run_epoch(model, examples, args, pad_id, *, optimizer=None, rng=None) -> float:
    order = list(range(len(examples)))
    if rng is not None:
        rng.shuffle(order)
    total_loss, n_batches = 0.0, 0
    for i in range(0, len(order), args.batch_size):
        batch = [examples[j] for j in order[i : i + args.batch_size]]
        input_ids, mask, soft = collate(batch, pad_id)
        if args.hard_labels:
            soft = harden(soft)
        if optimizer is None:
            with torch.no_grad():
                logits = model(input_ids, mask)
                parts = combined_loss(
                    logits,
                    soft,
                    mask,
                    model.crf,
                    alpha=args.alpha,
                    gamma=args.gamma,
                    use_crf=not args.no_crf_loss,
                )
        else:
            logits = model(input_ids, mask)
            parts = combined_loss(
                logits,
                soft,
                mask,
                model.crf,
                alpha=args.alpha,
                gamma=args.gamma,
                use_crf=not args.no_crf_loss,
            )
            optimizer.zero_grad()
            parts.total.backward()
            optimizer.step()
        total_loss += parts.total.item()
        n_batches += 1
    return total_loss / max(n_batches, 1)


def write_data_jsonl(path: Path, docs: list[Document]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for doc in docs:
            f.write(
                json.dumps(
                    {
                        "text": doc.text,
                        "spans": [[s.start, s.end, s.label, s.text] for s in doc.spans],
                        "families": doc.families,
                    }
                )
                + "\n"
            )


def ablation_slug(args) -> str | None:
    parts = []
    if args.hard_labels:
        parts.append("hard_labels")
    if args.gamma != 2.0:
        parts.append(f"gamma{args.gamma:g}")
    if args.no_crf_loss:
        parts.append("no_crf")
    return "_".join(parts) or None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr-head", type=float, default=5e-4)
    parser.add_argument("--lr-encoder", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=SEED_TRAIN)
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--hard-labels", action="store_true")
    parser.add_argument("--gamma", type=float, default=2.0)
    parser.add_argument("--no-crf-loss", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    slug = ablation_slug(args)

    print("generating corpora...", flush=True)
    candidates = generate_corpus(N_CANDIDATES, seed=SEED_TRAIN)
    train_docs = sample_training_set(candidates, N_TRAIN, seed=SEED_TRAIN)
    val_docs = generate_corpus(N_VAL, seed=SEED_VAL)
    eval_docs = generate_dense_eval(N_EVAL_DENSE, seed=SEED_EVAL)

    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)
    print("computing teacher soft labels...", flush=True)
    train_examples = encode_docs(train_docs, tokenizer)
    val_examples = encode_docs(val_docs, tokenizer)

    model = pretrained_student()
    optimizer = torch.optim.AdamW(
        [
            {"params": model.encoder.parameters(), "lr": args.lr_encoder},
            {
                "params": list(model.head.parameters()) + list(model.crf.parameters()),
                "lr": args.lr_head,
            },
        ]
    )

    pad_id = tokenizer.pad_token_id
    started = time.monotonic()
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = run_epoch(
            model, train_examples, args, pad_id, optimizer=optimizer, rng=rng
        )
        model.eval()
        val_loss = run_epoch(model, val_examples, args, pad_id)
        print(
            f"epoch {epoch}/{args.epochs}  train_loss={train_loss:.4f}  "
            f"val_loss={val_loss:.4f}  ({time.monotonic() - started:.0f}s)",
            flush=True,
        )

    print("evaluating on the entity-dense set...", flush=True)
    from app.deidentification.inference import Deidentifier

    model.eval()
    deid = Deidentifier(model, tokenizer)
    metrics = evaluate(deid.predict_spans, eval_docs)
    metrics["caveat"] = SYNTHETIC_CAVEAT
    metrics["train_seconds"] = round(time.monotonic() - started, 1)
    metrics["args"] = {
        k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()
    }
    print(json.dumps({k: v for k, v in metrics.items() if k != "args"}, indent=2))

    artifacts = args.artifacts_dir
    artifacts.mkdir(parents=True, exist_ok=True)
    if slug:
        # Ablation: metrics only, never the shipped weights.
        (artifacts / f"metrics_{slug}.json").write_text(
            json.dumps(metrics, indent=2) + "\n"
        )
        print(f"ablation metrics -> metrics_{slug}.json")
        return

    if not passes_gate(metrics):
        print("WARNING: recall gate failed (overall >= 0.90, per-type >= 0.85)")

    save_student(model, artifacts)
    tokenizer.save_pretrained(artifacts / "tokenizer")
    (artifacts / "labels.json").write_text(json.dumps(LABELS, indent=2) + "\n")
    (artifacts / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (artifacts / "config.json").write_text(
        json.dumps(
            {
                "encoder": ENCODER_NAME,
                "num_labels": NUM_LABELS,
                "max_length": MAX_LENGTH,
                "n_candidates": N_CANDIDATES,
                "n_train": N_TRAIN,
                "n_val": N_VAL,
                "n_eval_dense": N_EVAL_DENSE,
                "seed_train": SEED_TRAIN,
                "seed_val": SEED_VAL,
                "seed_eval": SEED_EVAL,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "lr_head": args.lr_head,
                "lr_encoder": args.lr_encoder,
                "alpha": args.alpha,
                "gamma": args.gamma,
            },
            indent=2,
        )
        + "\n"
    )
    write_data_jsonl(artifacts / "data" / "train.jsonl", train_docs)
    write_data_jsonl(artifacts / "data" / "val.jsonl", val_docs)
    write_data_jsonl(artifacts / "data" / "eval_dense.jsonl", eval_docs)
    print(f"artifacts -> {artifacts}")


if __name__ == "__main__":
    main()
