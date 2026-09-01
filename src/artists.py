"""Resolve a Spotify artist *id* from the artist *name* the embed gives us.

The embed's per-track `subtitle` is a comma-joined artist string ("Angelina
Mango, Marco Mengoni") with no ids. For each name we want an `artist_id`:

  1. our own data — `social_golden_data.spotify_track_artists`, matched on the
     normalized artist name (any track that artist has ever appeared on);
  2. failing that, one Apify call (the same actor ASP uses) with the track's
     `/track/{id}` URL, whose response carries an `artists` list of {id, name}.

`ArtistResolver` batches the Apify fallback: the pipeline first asks it what it
already knows, collects the track ids with at least one unresolved artist, then
does a single `enrich_via_apify(...)` call before building the rows.
"""

import logging
import os
from collections.abc import Iterable

from sqlalchemy import Engine, text

from src.consts import APIFY_API_KEY_ENV, SPOTIFY_ACTOR_ID, SPOTIFY_TRACK_URL
from src.db import retry_on_error

logger = logging.getLogger(__name__)

# Track URLs per Apify actor call. Keeps a single run bounded even when a lot of
# the day's tracks are new to us.
APIFY_BATCH_SIZE = 100


def normalize(value: str | None) -> str:
    """Lower-case and strip, for case-insensitive name comparison."""
    return (value or "").strip().casefold()


def split_artist_names(subtitle: str | None) -> list[str]:
    """Split the embed's joined artist string into individual names.

    The embed joins credited artists with ", "; splitting on comma is right for
    the overwhelming majority (a name that itself contains a comma, e.g. "Tyler,
    The Creator", is the rare exception and would be split — accepted).
    """
    if not subtitle:
        return []
    return [part.strip() for part in subtitle.split(",") if part.strip()]


class ArtistResolver:
    """Name -> artist_id lookup: our DB first, batched Apify fallback second."""

    def __init__(self, engine: Engine, *, use_apify: bool = True) -> None:
        self.engine = engine
        self.use_apify = use_apify
        # normalized artist name -> artist_id, from spotify_track_artists
        self._db_map: dict[str, str] = {}
        # track_id -> {normalized artist name -> artist_id}, from Apify
        self._apify_by_track: dict[str, dict[str, str]] = {}
        # normalized artist name -> artist_id, from Apify (any track)
        self._apify_name_map: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # our data                                                          #
    # ------------------------------------------------------------------ #
    def load_db_map(self) -> None:
        """Load every (artist_name -> artist_id) pair we already have."""
        sql = text(
            "SELECT DISTINCT artist_name, artist_id "
            "FROM social_golden_data.spotify_track_artists "
            "WHERE artist_name IS NOT NULL AND artist_id IS NOT NULL"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(sql).all()
        for artist_name, artist_id in rows:
            self._db_map.setdefault(normalize(artist_name), artist_id)
        logger.info("loaded %d distinct artist names from our data", len(self._db_map))

    def is_known(self, name: str) -> bool:
        """True when `name` already resolves without needing Apify."""
        key = normalize(name)
        return key in self._db_map or key in self._apify_name_map

    # ------------------------------------------------------------------ #
    # Apify fallback                                                     #
    # ------------------------------------------------------------------ #
    def enrich_via_apify(self, track_ids: Iterable[str]) -> None:
        """One actor call for all `track_ids`; cache their artist id/name pairs."""
        wanted = sorted({t for t in track_ids if t})
        if not wanted or not self.use_apify:
            return

        token = os.environ.get(APIFY_API_KEY_ENV)
        if not token:
            logger.warning(
                "%s not set - skipping Apify enrichment for %d tracks "
                "(artist_id stays NULL where our data has no match)",
                APIFY_API_KEY_ENV, len(wanted),
            )
            return

        try:
            from apify_client import ApifyClient
        except ImportError:
            logger.warning("apify-client not installed - skipping Apify enrichment")
            return

        client = ApifyClient(token)
        for start in range(0, len(wanted), APIFY_BATCH_SIZE):
            batch = wanted[start : start + APIFY_BATCH_SIZE]
            urls = [{"url": SPOTIFY_TRACK_URL.format(id=t)} for t in batch]
            try:
                items = self._run_actor(client, urls)
            except Exception:
                logger.exception(
                    "Apify actor call failed for a batch of %d tracks - "
                    "artist_id stays NULL for those",
                    len(batch),
                )
                continue

            for item in items:
                track_id = item.get("id")
                if not track_id:
                    continue
                bucket = self._apify_by_track.setdefault(track_id, {})
                for artist in item.get("artists") or []:
                    artist_id, artist_name = artist.get("id"), artist.get("name")
                    if not artist_id or not artist_name:
                        continue
                    key = normalize(artist_name)
                    bucket.setdefault(key, artist_id)
                    self._apify_name_map.setdefault(key, artist_id)

        logger.info(
            "Apify enrichment: got artists for %d/%d tracks",
            len(self._apify_by_track), len(wanted),
        )

    @retry_on_error(max_retries=3, delay=5.0, backoff=2.0)
    def _run_actor(self, client, urls: list[dict]) -> list[dict]:
        """Run the Apify Spotify actor and return its dataset items."""
        run = client.actor(SPOTIFY_ACTOR_ID).call(run_input={"urls": urls})
        return list(client.dataset(run["defaultDatasetId"]).iterate_items())

    # ------------------------------------------------------------------ #
    # resolution                                                        #
    # ------------------------------------------------------------------ #
    def resolve(self, track_id: str, name: str) -> str | None:
        """Best artist_id for `name` on `track_id`, or None.

        Apify's per-track credits win (they are specific to this recording),
        then a loose containment match inside that track's credits (the embed
        name and Spotify's canonical name can differ slightly), then either
        name map.
        """
        key = normalize(name)
        if not key:
            return None

        per_track = self._apify_by_track.get(track_id, {})
        if key in per_track:
            return per_track[key]
        for other_key, artist_id in per_track.items():
            if key in other_key or other_key in key:
                return artist_id

        return self._db_map.get(key) or self._apify_name_map.get(key)
