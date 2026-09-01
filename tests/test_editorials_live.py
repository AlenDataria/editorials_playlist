"""Live check: does every tracked editorial actually return a track list?

This talks to the real Spotify embed endpoint (no auth), one request per
playlist in `EDITORIALS`. It is NOT a unit test - it is network-dependent and
Spotify can change the embed shape or pull a playlist at any time - so it is
skipped unless `RUN_LIVE_TESTS=1` is set:

    RUN_LIVE_TESTS=1 uv run python -m pytest tests/test_editorials_live.py -v -s

`test_editorials_report` prints a per-playlist table (OK / UNAVAILABLE / ERROR)
and is the one to read when you just want "are all editorials answering?".
"""

import os
import time

import pytest
import requests

from src.consts import EDITORIALS, HTTP_HEADERS, REQUEST_DELAY
from src.embed import PlaylistUnavailable, fetch_playlist_tracklist

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="live network test - set RUN_LIVE_TESTS=1 to run",
)

# Playlists we KNOW the embed endpoint does not serve. Empty now that Viral 50 -
# Italia (the only known-404 one) has been dropped from EDITORIALS.
EXPECTED_UNAVAILABLE: set[str] = set()


@pytest.fixture(scope="module")
def http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


@pytest.mark.parametrize("ed", EDITORIALS, ids=lambda e: e.playlist_id)
def test_editorial_returns_tracklist(ed, http_session):
    """Each editorial either returns a non-empty track list, or is a
    known-unavailable one that raises PlaylistUnavailable."""
    try:
        tracks = fetch_playlist_tracklist(ed.playlist_id, http_session)
    except PlaylistUnavailable:
        if ed.playlist_id in EXPECTED_UNAVAILABLE:
            pytest.xfail(f"{ed.name}: not served via embed (known)")
        raise
    finally:
        time.sleep(REQUEST_DELAY)

    assert ed.playlist_id not in EXPECTED_UNAVAILABLE, (
        f"{ed.name} was expected to be unavailable but returned "
        f"{len(tracks)} tracks - update EXPECTED_UNAVAILABLE"
    )
    assert tracks, f"{ed.name} ({ed.playlist_id}) returned an empty track list"
    assert all(t.spotify_id for t in tracks), f"{ed.name}: a track has no spotify_id"


def test_editorials_report(http_session):
    """Fetch every editorial, print a summary table, and fail if any playlist
    we expect to work returned nothing."""
    rows: list[tuple[str, str, str]] = []
    unexpected_failures: list[str] = []

    for ed in EDITORIALS:
        try:
            tracks = fetch_playlist_tracklist(ed.playlist_id, http_session)
        except PlaylistUnavailable:
            status = "UNAVAILABLE (404 embed)"
            if ed.playlist_id not in EXPECTED_UNAVAILABLE:
                unexpected_failures.append(f"{ed.name}: unexpectedly UNAVAILABLE")
        except Exception as e:  # noqa: BLE001 - report, don't abort the sweep
            status = f"ERROR: {type(e).__name__}: {e}"
            unexpected_failures.append(f"{ed.name}: {status}")
        else:
            status = f"OK ({len(tracks)} tracks)"
            if not tracks:
                unexpected_failures.append(f"{ed.name}: empty track list")
            if ed.playlist_id in EXPECTED_UNAVAILABLE:
                unexpected_failures.append(
                    f"{ed.name}: expected UNAVAILABLE but got {len(tracks)} tracks"
                )
        rows.append((ed.name, ed.playlist_id, status))
        time.sleep(REQUEST_DELAY)

    width = max(len(name) for name, _, _ in rows)
    print(f"\n\nEditorials live check - {len(rows)} playlists\n" + "-" * (width + 45))
    for name, pid, status in rows:
        print(f"{name:<{width}}  {pid}  {status}")
    print("-" * (width + 45))
    ok = sum(1 for _, _, s in rows if s.startswith("OK"))
    print(f"{ok}/{len(rows)} returned a track list\n")

    assert not unexpected_failures, "unexpected results:\n" + "\n".join(unexpected_failures)
