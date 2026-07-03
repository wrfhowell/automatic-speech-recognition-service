import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.api.transcript import decode_cursor, encode_cursor


def test_cursor_round_trip():
    t = datetime(2026, 7, 2, 12, 30, 45, 123456, tzinfo=UTC)
    job_id = uuid.uuid4()
    decoded_t, decoded_id = decode_cursor(encode_cursor(t, job_id))
    assert decoded_t == t
    assert decoded_id == job_id


@pytest.mark.parametrize("bad", ["", "garbage", "e30=", "aGVsbG8=", "!!!!"])
def test_cursor_garbage_rejected(bad):
    with pytest.raises(HTTPException) as exc:
        decode_cursor(bad)
    assert exc.value.status_code == 400
