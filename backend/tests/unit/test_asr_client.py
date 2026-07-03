import httpx
import pytest
import respx

from app.core.asr_client import AsrClient, AsrKind

BASE = "http://mock-asr:3001"


@pytest.fixture
async def asr():
    client = AsrClient(base_url=BASE, timeout_seconds=1.0)
    yield client
    await client.aclose()


@respx.mock
async def test_200_maps_to_ok(asr):
    respx.get(f"{BASE}/get-asr-output").respond(
        200, json={"path": "audio-file-1.wav", "transcript": "hello world"}
    )
    result = await asr.get_transcript("audio-file-1.wav")
    assert result.kind == AsrKind.OK
    assert result.transcript == "hello world"


@respx.mock
async def test_404_maps_to_not_found(asr):
    respx.get(f"{BASE}/get-asr-output").respond(404, json={"error": "File not found"})
    assert (await asr.get_transcript("nope.wav")).kind == AsrKind.NOT_FOUND


@respx.mock
async def test_500_maps_to_transient(asr):
    respx.get(f"{BASE}/get-asr-output").respond(500, json={"error": "Internal server error"})
    assert (await asr.get_transcript("audio-file-1.wav")).kind == AsrKind.TRANSIENT


@respx.mock
async def test_429_maps_to_rate_limited(asr):
    respx.get(f"{BASE}/get-asr-output").respond(429, json={"error": "Too many requests"})
    assert (await asr.get_transcript("audio-file-1.wav")).kind == AsrKind.RATE_LIMITED


@respx.mock
async def test_timeout_maps_to_transient(asr):
    respx.get(f"{BASE}/get-asr-output").mock(side_effect=httpx.ReadTimeout("timed out"))
    result = await asr.get_transcript("audio-file-1.wav")
    assert result.kind == AsrKind.TRANSIENT
    assert result.detail == "timeout"


@respx.mock
async def test_connect_error_maps_to_transient(asr):
    respx.get(f"{BASE}/get-asr-output").mock(side_effect=httpx.ConnectError("refused"))
    assert (await asr.get_transcript("audio-file-1.wav")).kind == AsrKind.TRANSIENT


@respx.mock
async def test_path_is_passed_as_query_param(asr):
    route = respx.get(f"{BASE}/get-asr-output", params={"path": "audio-file-3.wav"}).respond(
        200, json={"path": "audio-file-3.wav", "transcript": "x"}
    )
    await asr.get_transcript("audio-file-3.wav")
    assert route.called
