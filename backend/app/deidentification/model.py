"""CIPHER student: bert-tiny encoder + MLP head + CRF.

save_student/load_student round-trip through a directory of committed
artifacts (encoder_config.json + student.pt): loading rebuilds the encoder
from config and restores all weights from the state dict, so the demo
never touches the HuggingFace hub at runtime.
"""

from pathlib import Path

import torch
from torch import Tensor, nn
from transformers import BertConfig, BertModel

from app.deidentification.crf import CRF
from app.deidentification.labels import NUM_LABELS
from app.deidentification.viterbi import viterbi_decode

ENCODER_NAME = "prajjwal1/bert-tiny"
# bert-tiny's hub repo predates model_type/tokenizer.json; it shares the
# standard 30,522-entry uncased WordPiece vocab, so the tokenizer comes
# from bert-base-uncased (which ships a fast tokenizer.json).
TOKENIZER_NAME = "bert-base-uncased"
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

_WEIGHTS_FILE = "student.pt"
_ENCODER_CONFIG_FILE = "encoder_config.json"


class DeidStudent(nn.Module):
    def __init__(
        self, encoder: BertModel, dropout: float = 0.1, num_labels: int = NUM_LABELS
    ):
        super().__init__()
        self.encoder = encoder
        hidden = encoder.config.hidden_size
        self.head = nn.Sequential(
            nn.Linear(hidden, hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, num_labels),
        )
        self.crf = CRF(num_labels)

    def forward(self, input_ids: Tensor, attention_mask: Tensor) -> Tensor:
        """-> emissions [B, T, num_labels]"""
        hidden = self.encoder(
            input_ids=input_ids, attention_mask=attention_mask
        ).last_hidden_state
        return self.head(hidden)

    @torch.no_grad()
    def decode(self, emissions: Tensor, mask: Tensor) -> list[list[int]]:
        return viterbi_decode(
            emissions,
            mask,
            self.crf.constrained_transitions(),
            self.crf.constrained_starts(),
            self.crf.end_transitions,
        )


def pretrained_student(dropout: float = 0.1) -> DeidStudent:
    """Fresh student with hub-downloaded encoder weights (training only)."""
    return DeidStudent(BertModel.from_pretrained(ENCODER_NAME), dropout=dropout)


def save_student(model: DeidStudent, artifacts_dir: Path) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    model.encoder.config.to_json_file(artifacts_dir / _ENCODER_CONFIG_FILE)
    torch.save(model.state_dict(), artifacts_dir / _WEIGHTS_FILE)


def load_student(artifacts_dir: Path = ARTIFACTS_DIR) -> DeidStudent:
    config = BertConfig.from_json_file(artifacts_dir / _ENCODER_CONFIG_FILE)
    model = DeidStudent(BertModel(config))
    state = torch.load(
        artifacts_dir / _WEIGHTS_FILE, map_location="cpu", weights_only=True
    )
    model.load_state_dict(state)
    return model.eval()
