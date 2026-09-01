"""Fetch a playlist's current track list from Spotify's public embed page.

The embed page (`open.spotify.com/embed/playlist/{id}`) needs no auth. Its HTML
carries a `<script id="__NEXT_DATA__">` JSON blob; the track list lives at
`props.pageProps.state.data.entity.trackList`, already in playlist order.

This JSON shape is not a documented API and can change without notice, so all the
parsing is isolated here and covered by tests/test_embed.py with a saved fixture.
Known limits: the embed returns at most ~100 tracks (a longer playlist is
silently truncated) and it does NOT carry an album name per track.
"""

import json
import logging
import re
from dataclasses import dataclass

import requests

from src.consts import (
    EMBED_TRACK_CAP,
    EMBED_URL,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF,
    RETRY_DELAY,
)
from src.db import retry_on_error

logger = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)


@dataclass(frozen=True)
class PlaylistTrack:
    """One track as listed in an editorial playlist."""

    position: int          # 1-based rank in the playlist
    spotify_id: str        # from the entry's "spotify:track:<id>" uri
    title: str             # playlist-side title (may include "(con ...)" etc.)
    artists: str           # playlist-side artist string ("Artist A, Artist B")


class EmbedParseError(RuntimeError):
    """The embed HTML did not contain a parseable __NEXT_DATA__ / trackList."""


class PlaylistUnavailable(RuntimeError):
    """The embed page rendered a 404-shaped payload for this playlist id.

    The embed endpoint intermittently returns this for playlists that are
    perfectly fine, so `fetch_playlist_tracklist` retries it like any other
    transient error. A playlist that is genuinely not served (it used to be the
    Viral 50 charts) simply exhausts the retries and is then skipped by the
    caller.
    """


def parse_tracklist(html: str) -> list[PlaylistTrack]:
    """Extract the ordered track list from an embed page's HTML."""
    m = _NEXT_DATA_RE.search(html)
    if not m:
        raise EmbedParseError("no __NEXT_DATA__ script tag found")

    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise EmbedParseError(f"__NEXT_DATA__ is not valid JSON: {e}") from e

    page_props = data.get("props", {}).get("pageProps", {})
    if page_props.get("status") == 404 or page_props.get("state") is None:
        raise PlaylistUnavailable("embed rendered a 404 for this playlist")

    try:
        entity = page_props["state"]["data"]["entity"]
        raw_tracks = entity["trackList"]
    except (KeyError, TypeError) as e:
        raise EmbedParseError(f"unexpected __NEXT_DATA__ shape: {e}") from e

    tracks: list[PlaylistTrack] = []
    for i, t in enumerate(raw_tracks, start=1):
        if not isinstance(t, dict) or t.get("entityType") != "track":
            continue
        uri = t.get("uri") or ""
        if not uri.startswith("spotify:track:"):
            continue
        tracks.append(
            PlaylistTrack(
                position=i,
                spotify_id=uri.split(":")[-1],
                title=t.get("title") or "",
                artists=t.get("subtitle") or "",
            )
        )

    if len(raw_tracks) >= EMBED_TRACK_CAP:
        logger.warning(
            "playlist returned %d entries (embed cap is %d) - list may be truncated",
            len(raw_tracks),
            EMBED_TRACK_CAP,
        )
    return tracks


@retry_on_error(
    max_retries=MAX_RETRIES,
    delay=RETRY_DELAY,
    backoff=RETRY_BACKOFF,
    exceptions=(requests.RequestException, EmbedParseError, PlaylistUnavailable),
)
def fetch_playlist_tracklist(
    playlist_id: str, session: requests.Session
) -> list[PlaylistTrack]:
    """GET the embed page for `playlist_id` and return its ordered track list."""
    resp = session.get(
        EMBED_URL.format(id=playlist_id), timeout=REQUEST_TIMEOUT
    )
    resp.raise_for_status()
    return parse_tracklist(resp.text)
