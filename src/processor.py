"""EditorialsTracker: the daily run.

For each playlist in `EDITORIALS`: fetch its current track list from the embed
endpoint, match it against our campaign-active Spotify tracks, and write one
`editorial_playlist_entries` snapshot row per match for today.

Matching is layered:
  1. exact `spotify_id` equality (the embed gives us the track id directly);
  2. fuzzy title+artist fallback (src/matching.py) for tracks our DB holds under
     a different id than the one in the editorial.

Resilience mirrors song_resolver_tracker: commit per playlist so a later failure
never loses earlier progress, and a playlist that fails is logged and skipped
rather than aborting the whole run.
"""

import logging
import time
from datetime import date

import requests
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlmodel import Session, select

from src.consts import EDITORIALS, HTTP_HEADERS, REQUEST_DELAY, Editorial
from src.db import create_db_engine, db_config_from_env
from src.embed import PlaylistTrack, PlaylistUnavailable, fetch_playlist_tracklist
from src.matching import is_track_match
from src.models import (
    EditorialPlaylistEntry,
    SourceTrack,
    SpotifyTrack,
    SpotifyTrackArtists,
)

logger = logging.getLogger(__name__)


class EditorialsTracker:
    """Snapshot our tracks' presence and position in the tracked editorials."""

    def __init__(self) -> None:
        self.engine = create_db_engine(db_config_from_env())
        self.session = requests.Session()
        self.session.headers.update(HTTP_HEADERS)

    def _ensure_table(self) -> None:
        """Create editorial_playlist_entries if missing (no migration tool here).

        `checkfirst=True` only issues CREATE when the table is absent, so a role
        without DDL rights still works once the table has been created by hand
        (see sql/editorial_playlist_entries.ddl.sql).
        """
        try:
            EditorialPlaylistEntry.__table__.create(
                bind=self.engine, checkfirst=True
            )
        except Exception:
            logger.exception(
                "could not create %s - have a DBA create it from "
                "sql/editorial_playlist_entries.ddl.sql, then re-run",
                EditorialPlaylistEntry.__tablename__,
            )
            raise

    # ------------------------------------------------------------------ #
    # run                                                                #
    # ------------------------------------------------------------------ #
    def run(self, dry_run: bool = False) -> None:
        today = date.today()
        if not dry_run:
            self._ensure_table()
        with Session(self.engine) as db:
            our_tracks = self._active_spotify_tracks(db)
            by_id = {t.spotify_id: t for t in our_tracks}
            logger.info("loaded %d campaign-active spotify tracks", len(our_tracks))

            total_rows = 0
            for ed in EDITORIALS:
                try:
                    tracklist = fetch_playlist_tracklist(ed.playlist_id, self.session)
                except PlaylistUnavailable:
                    # Known-tolerated: some Spotify charts (Viral 50) are not
                    # served via the embed endpoint. Skip quietly, no traceback.
                    logger.warning(
                        "editorial %s (%s) is not available via embed - skipping",
                        ed.name, ed.playlist_id,
                    )
                    continue
                except Exception:
                    logger.exception("skipping editorial %s (%s)", ed.name, ed.playlist_id)
                    continue

                rows = self._match_rows(ed, tracklist, our_tracks, by_id, today)
                logger.info(
                    "%s: %d/%d playlist tracks are ours", ed.name, len(rows), len(tracklist)
                )

                if dry_run:
                    for r in rows:
                        logger.info(
                            "  would write: pos=%3d  %s - %s  [%s]",
                            r.position, r.track_name, r.artist_name, r.spotify_id,
                        )
                    continue

                for r in rows:
                    db.add(r)
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("commit failed for editorial %s", ed.playlist_id)
                    continue
                total_rows += len(rows)
                time.sleep(REQUEST_DELAY)

            logger.info(
                "done: wrote %d snapshot rows for %s across %d editorials",
                total_rows, today, len(EDITORIALS),
            )

    # ------------------------------------------------------------------ #
    # helpers                                                            #
    # ------------------------------------------------------------------ #
    def _active_spotify_tracks(self, session: Session) -> list[SourceTrack]:
        """Every campaign-active Spotify track with its artists, one row per track.

        `active IS NOT false` keeps rows where active is true or NULL. Artists are
        aggregated in a stable order (by artist_id) so ", ".join is deterministic.
        Same query shape as song_resolver_tracker's load_spotify_tracks.
        """
        statement = (
            select(
                SpotifyTrack.spotify_id,
                SpotifyTrack.track_name,
                SpotifyTrack.album_name,
                func.array_agg(
                    aggregate_order_by(
                        SpotifyTrackArtists.artist_name,
                        SpotifyTrackArtists.artist_id,
                    )
                )
                .filter(SpotifyTrackArtists.artist_name.isnot(None))
                .label("artist_names"),
            )
            .join(
                SpotifyTrackArtists,
                SpotifyTrackArtists.spotify_track_id == SpotifyTrack.spotify_id,
                isouter=True,
            )
            .where(SpotifyTrack.active.isnot(False))
            .group_by(SpotifyTrack.spotify_id)
        )

        tracks: list[SourceTrack] = []
        for row in session.exec(statement):
            tracks.append(
                SourceTrack(
                    spotify_id=row.spotify_id,
                    track_name=row.track_name,
                    album_name=row.album_name,
                    artist_names=list(row.artist_names or []),
                )
            )
        return tracks

    def _match_rows(
        self,
        editorial: Editorial,
        tracklist: list[PlaylistTrack],
        our_tracks: list[SourceTrack],
        by_id: dict[str, SourceTrack],
        today: date,
    ) -> list[EditorialPlaylistEntry]:
        """Turn a playlist track list into snapshot rows for our matched tracks.

        Walks the playlist in order, so the first time a track of ours is seen we
        record its (lowest) position. A track of ours appearing twice in the same
        playlist (rare) keeps the better position.
        """
        # spotify_id (ours) -> best position seen so far
        best_position: dict[str, int] = {}
        matched_by: dict[str, str] = {}

        for pt in tracklist:
            our = by_id.get(pt.spotify_id)
            how = "spotify_id"
            if our is None:
                our = next(
                    (
                        t
                        for t in our_tracks
                        if is_track_match(
                            t.track_name, t.artist_names, pt.title, pt.artists
                        )
                    ),
                    None,
                )
                how = "fuzzy"
            if our is None:
                continue

            if our.spotify_id not in best_position or pt.position < best_position[our.spotify_id]:
                best_position[our.spotify_id] = pt.position
                matched_by[our.spotify_id] = how

        rows: list[EditorialPlaylistEntry] = []
        for spotify_id, position in best_position.items():
            our = by_id[spotify_id]
            if matched_by[spotify_id] == "fuzzy":
                logger.debug(
                    "fuzzy match in %s: our '%s' <- playlist pos %d",
                    editorial.name, our.track_name, position,
                )
            rows.append(
                EditorialPlaylistEntry(
                    playlist_id=editorial.playlist_id,
                    spotify_id=spotify_id,
                    snapshot_date=today,
                    playlist_name=editorial.name,
                    track_name=our.track_name,
                    artist_name=", ".join(our.artist_names) or None,
                    album_name=our.album_name,
                    position=position,
                )
            )
        rows.sort(key=lambda r: r.position)
        return rows
