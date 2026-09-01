"""Unit tests for the stint diff in src/processor.py."""

from src.processor import diff_playlist


def test_first_run_opens_everything():
    to_open, to_close, to_keep = diff_playlist({"a", "b"}, set())
    assert to_open == {"a", "b"}
    assert to_close == set()
    assert to_keep == set()


def test_steady_state_keeps_everything():
    to_open, to_close, to_keep = diff_playlist({"a", "b"}, {"a", "b"})
    assert to_open == set()
    assert to_close == set()
    assert to_keep == {"a", "b"}


def test_new_and_gone_together():
    to_open, to_close, to_keep = diff_playlist({"a", "c"}, {"a", "b"})
    assert to_open == {"c"}   # c is new
    assert to_close == {"b"}  # b left
    assert to_keep == {"a"}   # a stays


def test_returning_track_is_reopened():
    # 'a' is not currently open (it left earlier) and is back now -> to_open
    to_open, to_close, to_keep = diff_playlist({"a"}, set())
    assert to_open == {"a"}
    assert to_close == set()
