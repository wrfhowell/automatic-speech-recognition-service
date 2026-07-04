import pytest
from pydantic import ValidationError

from app.api.schemas import TranscribeRequest


def test_valid_request_strips_paths():
    req = TranscribeRequest.model_validate(
        {"audioChunkPaths": [" a.wav ", "b.wav"], "userId": "u1"}
    )
    assert req.audio_chunk_paths == ["a.wav", "b.wav"]
    assert req.user_id == "u1"


@pytest.mark.parametrize(
    "paths",
    [[], ["a.wav", "  "], ["x.wav"] * 65],
)
def test_invalid_paths_rejected(paths):
    with pytest.raises(ValidationError):
        TranscribeRequest.model_validate({"audioChunkPaths": paths, "userId": "u1"})


def test_empty_user_rejected():
    with pytest.raises(ValidationError):
        TranscribeRequest.model_validate({"audioChunkPaths": ["a.wav"], "userId": ""})
