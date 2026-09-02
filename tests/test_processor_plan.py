"""Unit tests for the pure decision helpers in src/processor.py."""

from src.consts import PARTIAL_RESPONSE_DROP
from src.processor import diff_playlist, is_partial_response


# --- diff_playlist ---------------------------------------------------------- #

def test_first_run_opens_everything():
    to_open, to_close, to_keep = diff_playlist({"a", "b"}, set())
    assert to_open == {"a", "b"}
    assert to_close == set()
    assert to_keep == set()


def test_steady_state_keeps_everything():
    to_open, to_close, to_keep = diff_playlist({"a", "b"}, {"a", "b"})
    assert (to_open, to_close, to_keep) == (set(), set(), {"a", "b"})


def test_new_and_gone_together():
    to_open, to_close, to_keep = diff_playlist({"a", "c"}, {"a", "b"})
    assert to_open == {"c"}
    assert to_close == {"b"}
    assert to_keep == {"a"}


def test_returning_track_is_reopened():
    to_open, to_close, _ = diff_playlist({"a"}, set())
    assert to_open == {"a"}
    assert to_close == set()


# --- is_partial_response --------------------------------------------------- #

def test_partial_when_drop_at_or_above_threshold():
    assert is_partial_response(80, 80 + PARTIAL_RESPONSE_DROP) is True
    assert is_partial_response(0, PARTIAL_RESPONSE_DROP) is True


def test_not_partial_for_small_drop_or_growth():
    assert is_partial_response(80, 80 + PARTIAL_RESPONSE_DROP - 1) is False
    assert is_partial_response(100, 100) is False
    assert is_partial_response(120, 100) is False  # playlist grew


def test_not_partial_on_first_run_when_nothing_open():
    assert is_partial_response(50, 0) is False
