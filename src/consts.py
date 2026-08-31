"""Static configuration for the editorials_playlist pipeline.

`EDITORIALS` is the fixed list of Spotify Italy editorial playlists we track.
There is no DB registry table: the list (and its metadata) lives here and is
changed with a commit + redeploy. `viral_road` is documentation-only for now —
nothing in the code reads it (see "Documentazione editorials_playlist.md",
Step 4).
"""

from dataclasses import dataclass

# Postgres schema holding the golden social tables (same as the other pipelines).
DB_SCHEMA = "social_golden_data"

# Public, unauthenticated embed page for a playlist. The track list is parsed out
# of the `__NEXT_DATA__` JSON blob in the returned HTML (see src/embed.py).
EMBED_URL = "https://open.spotify.com/embed/playlist/{id}"

# The embed page is meant for browsers; a plain requests User-Agent gets a 403
# at the edge, so we send a browser-like one.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 30
# Seconds to wait between playlist fetches — the endpoint is public and we only
# hit it ~16 times per run, so this is politeness, not a hard rate limit.
REQUEST_DELAY: float = 1.0

# retry_on_error tuning for the embed fetch.
MAX_RETRIES = 4
RETRY_DELAY = 1.0
RETRY_BACKOFF = 2.0

# The embed page returns at most this many tracks; a playlist at or above the cap
# may be silently truncated (none of the tracked ones should reach it).
EMBED_TRACK_CAP = 100


@dataclass(frozen=True)
class Editorial:
    """One tracked editorial playlist.

    - playlist_id: the Spotify id (the part after /playlist/ in the URL).
    - name: stored on every snapshot row as `playlist_name`.
    - segment: who the placement matters most for — "major" | "emergent" | "both".
    - update_cadence: how often Spotify refreshes it — informational.
    - viral_road: documentation-only hint of the stage this playlist represents;
      not used by the pipeline yet.
    """

    playlist_id: str
    name: str
    segment: str
    update_cadence: str
    viral_road: str


# 16 playlists. EQUAL Italia intentionally excluded.
#
# NOTE: as of 2026-08 Spotify does not serve "Viral 50 - Italia" through the
# embed endpoint (it renders a 404). It is kept in the list on purpose: the
# pipeline skips it with a WARNING (not an error), so if Spotify re-enables the
# embed for it the data starts flowing with no code change. Viral 50 is the
# "breaking" signal for the future viral-road feature, so we want it wired up.
EDITORIALS: tuple[Editorial, ...] = (
    Editorial("37i9dQZEVXbKbvcwe5owJ1", "Viral 50 - Italia", "both", "daily", "breaking"),
    Editorial("37i9dQZEVXbIQnj7RRhdSX", "Top 50 - Italia", "major", "daily", "mainstream"),
    Editorial("37i9dQZF1DX01NP73ErE8b", "Alta Rotazione", "major", "multi_weekly", "mainstream"),
    Editorial("37i9dQZF1DX6wfQutivYYr", "Hot Hits Italia", "major", "twice_weekly", "mainstream"),
    Editorial("37i9dQZF1DXcuVttLeQxkh", "Hit Italiane", "major", "weekly", "mainstream"),
    Editorial("37i9dQZF1DX7zFcFgqJ2qf", "Big Italiani", "major", "weekly", "status"),
    Editorial("37i9dQZF1DWVKDF4ycOESi", "New Music Friday Italia", "both", "weekly_friday", "on_radar"),
    Editorial("37i9dQZF1DX1OQlaot30zi", "Novita Rap Italiano", "both", "weekly_friday", "on_radar"),
    Editorial("37i9dQZF1DX6O5gXioqvYB", "Novita Indie Italiano", "both", "weekly_friday", "on_radar"),
    Editorial("37i9dQZF1DX2c7QgpQBJFr", "nuovo pop Italia", "emergent", "weekly", "on_radar"),
    Editorial("37i9dQZF1DWYCIYGXn56uz", "GENERAZIONE Z", "emergent", "weekly", "gaining"),
    Editorial("37i9dQZF1DWW9tK1GiTdMf", "sanguegiovane", "emergent", "weekly", "gaining"),
    Editorial("37i9dQZF1DWZuIX5Q3yUjF", "anima R&B", "emergent", "weekly", "gaining"),
    Editorial("37i9dQZF1DWSxF6XNtQ9Rg", "Hit Rap Italiane", "both", "weekly", "mainstream"),
    Editorial("37i9dQZF1DX0KBgD4Jf5tY", "Fresh Finds Italia", "emergent", "weekly", "on_radar"),
    Editorial("37i9dQZF1DWVjDgOMO8jZl", "RADAR Italia", "emergent", "slow_rotation", "on_radar"),
)
