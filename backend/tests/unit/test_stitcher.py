from app.models import JobStatus
from app.workers.stitch_job import stitch_transcript, terminal_job_status

C, F = "COMPLETED", "FAILED"


def test_concatenates_in_ordinal_order_even_if_unsorted():
    chunks = [(2, C, "three"), (0, C, "one"), (1, C, "two")]
    assert stitch_transcript(chunks) == "one\n\ntwo\n\nthree"


def test_failed_chunk_marker_is_one_based():
    # Pinned: ordinal 1 (0-based) renders as "[chunk 2 unavailable]".
    chunks = [(0, C, "one"), (1, F, None), (2, C, "three")]
    assert stitch_transcript(chunks) == "one\n\n[chunk 2 unavailable]\n\nthree"


def test_transcript_whitespace_is_trimmed():
    assert stitch_transcript([(0, C, "\n  text  \n")]) == "text"


def test_all_completed_maps_to_completed():
    assert terminal_job_status([C, C, C]) == JobStatus.COMPLETED


def test_all_failed_maps_to_failed():
    assert terminal_job_status([F, F]) == JobStatus.FAILED


def test_mixed_maps_to_completed_with_errors():
    assert terminal_job_status([C, F, C]) == JobStatus.COMPLETED_WITH_ERRORS
