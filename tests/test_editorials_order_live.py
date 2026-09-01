"""Live check: is the embed's track ORDER the same order Spotify itself serves?

The embed `trackList` carries no position field - `src/embed.py` numbers tracks
purely by their order in that array. This test verifies that order against the
authoritative source: the Spotify Web API's
`GET /v1/playlists/{id}/tracks`, which returns items in playlist order.

Needs Spotify app credentials (client-credentials flow is enough - these are
public, Spotify-owned playlists). Create an app at
https://developer.spotify.com/dashboard and export:

    export SPOTIFY_CLIENT_ID=...
    export SPOTIFY_CLIENT_SECRET=...
    RUN_LIVE_TESTS=1 uv run python -m pytest tests/test_editorials_order_live.py -v -s

Skipped unless RUN_LIVE_TESTS=1 and both credentials are set.

Note: the embed caps at ~100 tracks, so only the first 100 positions are
compared. Order can also legitimately shift between the two calls if Spotify
refreshes the playlist in between - re-run if a single playlist disagrees.
"""

import base64
import os
import time

import pytest
import requests

from src.consts import EDITORIALS, HTTP_HEADERS, REQUEST_DELAY
from src.embed import PlaylistUnavailable, fetch_playlist_tracklist

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1" or not (CLIENT_ID and CLIENT_SECRET),
    reason="live test - needs RUN_LIVE_TESTS=1 and SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET",
)

EXPECTED_UNAVAILABLE: set[str] = set()  # Viral 50 (the only known-404) is no longer tracked
EMBED_CAP = 100


@pytest.fixture(scope="module")
def api_token() -> str:
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        headers={
            "Authorization": "Basic "
            + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]

    # Preflight: since 2025 the Web API returns 403 for every endpoint unless the
    # app owner's Spotify account has active Premium. Detect that once and skip
    # the whole module with Spotify's own message rather than failing 16 times.
    check = requests.get(
        "https://api.spotify.com/v1/playlists/37i9dQZEVXbIQnj7RRhdSX?fields=id",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if check.status_code == 403:
        pytest.skip(f"Spotify Web API unavailable for these credentials: {check.text.strip()}")
    check.raise_for_status()
    return token


@pytest.fixture(scope="module")
def http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HTTP_HEADERS)
    return s


def _api_track_ids(playlist_id: str, token: str) -> list[str]:
    """Ordered spotify track ids from the Web API (playlist order)."""
    ids: list[str] = []
    url = (
        f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        "?fields=next,items(track(id,type))&limit=100"
    )
    while url:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status()
        body = r.json()
        for it in body.get("items", []):
            tr = it.get("track") or {}
            if tr.get("type") == "track" and tr.get("id"):
                ids.append(tr["id"])
        url = body.get("next")
    return ids


@pytest.mark.parametrize("ed", EDITORIALS, ids=lambda e: e.playlist_id)
def test_embed_order_matches_web_api(ed, api_token, http_session):
    if ed.playlist_id in EXPECTED_UNAVAILABLE:
        pytest.skip(f"{ed.name}: not served via embed")

    try:
        embed_ids = [t.spotify_id for t in fetch_playlist_tracklist(ed.playlist_id, http_session)]
    except PlaylistUnavailable:
        pytest.skip(f"{ed.name}: embed returned 404")
    api_ids = _api_track_ids(ed.playlist_id, api_token)
    time.sleep(REQUEST_DELAY)

    # embed is capped; compare only the overlap from the top
    n = min(len(embed_ids), len(api_ids), EMBED_CAP)
    embed_head, api_head = embed_ids[:n], api_ids[:n]

    if embed_head == api_head:
        return

    # same set, different order -> real ordering bug; different set -> playlist
    # changed between the two calls (report either way with the first mismatch)
    first = next(i for i in range(n) if embed_head[i] != api_head[i])
    same_set = set(embed_head) == set(api_head)
    pytest.fail(
        f"{ed.name} ({ed.playlist_id}): order differs from position {first + 1} "
        f"(same tracks, reordered={same_set}); "
        f"embed={embed_head[first:first + 5]} api={api_head[first:first + 5]}"
    )


def test_order_report(api_token, http_session):
    """One-line-per-playlist summary of embed-vs-API order agreement."""
    rows = []
    mismatches = []
    for ed in EDITORIALS:
        if ed.playlist_id in EXPECTED_UNAVAILABLE:
            rows.append((ed.name, "skipped (not on embed)"))
            continue
        try:
            embed_ids = [t.spotify_id for t in fetch_playlist_tracklist(ed.playlist_id, http_session)]
        except PlaylistUnavailable:
            rows.append((ed.name, "skipped (embed 404)"))
            continue
        api_ids = _api_track_ids(ed.playlist_id, api_token)
        time.sleep(REQUEST_DELAY)

        n = min(len(embed_ids), len(api_ids), EMBED_CAP)
        if embed_ids[:n] == api_ids[:n]:
            rows.append((ed.name, f"OK - first {n} in same order"))
        else:
            first = next(i for i in range(n) if embed_ids[i] != api_ids[i])
            same_set = set(embed_ids[:n]) == set(api_ids[:n])
            tag = "REORDERED" if same_set else "CONTENT CHANGED mid-check"
            rows.append((ed.name, f"{tag} at pos {first + 1}"))
            if same_set:
                mismatches.append(f"{ed.name}: reordered at pos {first + 1}")

    width = max(len(n) for n, _ in rows)
    print("\n\nEmbed order vs Spotify Web API order\n" + "-" * (width + 40))
    for name, status in rows:
        print(f"{name:<{width}}  {status}")
    print("-" * (width + 40))

    assert not mismatches, "embed order does not match Spotify:\n" + "\n".join(mismatches)
