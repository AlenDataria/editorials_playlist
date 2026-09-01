"""Static configuration for the editorials_playlist pipeline.

`EDITORIALS` is the fixed list of Spotify Italy editorial playlists we track.
The list lives here and is changed with a commit + redeploy; every run also
upserts it into `social_golden_data.editorial_playlists` so the DB has a
readable registry (and a FK target for the history table).
"""

from dataclasses import dataclass

# Postgres schema holding the golden social tables (same as the other pipelines).
DB_SCHEMA = "social_golden_data"

# Public, unauthenticated embed page for a playlist. The track list is parsed out
# of the `__NEXT_DATA__` JSON blob in the returned HTML (see src/embed.py).
EMBED_URL = "https://open.spotify.com/embed/playlist/{id}"

# --- Apify: artist-id enrichment ------------------------------------------------
# The embed gives us the track id and an artist *name* string, but no artist id.
# When we can't resolve an artist id from social_golden_data.spotify_track_artists
# (by name), we fall back to the same Apify actor ASP uses, called with /track
# URLs; each returned item carries an `artists` list of {id, name}.
SPOTIFY_ACTOR_ID = "beatanalytics/spotify-play-count-scraper"
SPOTIFY_TRACK_URL = "https://open.spotify.com/track/{id}"
# Env var holding the Apify API token (same name as ASP's spotify pipeline).
APIFY_API_KEY_ENV = "SPOTIFY_API_KEY"

# --- Open-stint state file ----------------------------------------------------
# One JSON document tracks which (playlist, track) stints are currently open,
# with each track's start date and last-seen date. Persisted on S3 in
# production (bucket from S3_BUCKET_NAME, region from AWS_REGION); when
# S3_BUCKET_NAME is unset it falls back to a local file (dev / --dry-run).
STATE_S3_KEY = "editorial_playlist_state/open_stints.json"
STATE_LOCAL_PATH = "editorial_state.json"

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
# hit it ~15 times per run, so this is politeness, not a hard rate limit.
REQUEST_DELAY: float = 1.0

# retry_on_error tuning for the embed fetch.
MAX_RETRIES = 4
RETRY_DELAY = 1.0
RETRY_BACKOFF = 2.0

# The embed page returns at most this many tracks; a playlist at or above the cap
# may be silently truncated.
EMBED_TRACK_CAP = 100


@dataclass(frozen=True)
class Editorial:
    """One tracked editorial playlist.

    - playlist_id: the Spotify id (the part after /playlist/ in the URL).
    - name: stored as `playlist_name` on the registry and every history row.
    """

    playlist_id: str
    name: str


# Editorials we snapshot in full (every track + every artist), one row per
# (playlist, track, artist, day). EQUAL Italia intentionally excluded.
#
# Removed on purpose:
#   - "Viral 50 - Italia" (37i9dQZEVXbKbvcwe5owJ1): Spotify does not serve it via
#     the embed endpoint (renders a 404).
#   - "Big Italiani" (37i9dQZF1DX7zFcFgqJ2qf): status playlist, not part of the
#     signal we care about here.
EDITORIALS: tuple[Editorial, ...] = (
    Editorial("37i9dQZEVXbIQnj7RRhdSX", "Top 50 - Italia"),
    Editorial("37i9dQZF1DX01NP73ErE8b", "Alta Rotazione"),
    Editorial("37i9dQZF1DX6wfQutivYYr", "Hot Hits Italia"),
    Editorial("37i9dQZF1DXcuVttLeQxkh", "Hit Italiane"),
    Editorial("37i9dQZF1DWVKDF4ycOESi", "New Music Friday Italia"),
    Editorial("37i9dQZF1DX1OQlaot30zi", "Novita Rap Italiano"),
    Editorial("37i9dQZF1DX6O5gXioqvYB", "Novita Indie Italiano"),
    Editorial("37i9dQZF1DX2c7QgpQBJFr", "nuovo pop Italia"),
    Editorial("37i9dQZF1DWYCIYGXn56uz", "GENERAZIONE Z"),
    Editorial("37i9dQZF1DWW9tK1GiTdMf", "sanguegiovane"),
    Editorial("37i9dQZF1DWZuIX5Q3yUjF", "anima R&B"),
    Editorial("37i9dQZF1DWSxF6XNtQ9Rg", "Hit Rap Italiane"),
    Editorial("37i9dQZF1DX0KBgD4Jf5tY", "Fresh Finds Italia"),
    Editorial("37i9dQZF1DWVjDgOMO8jZl", "RADAR Italia"),
    Editorial("37i9dQZF1DWUQru3jd69v5", "Raptopia"),
)
