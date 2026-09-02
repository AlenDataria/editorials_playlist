"""EditorialsTracker: the daily run.

The pipeline keeps one row per *stint* — a continuous period a track spent in an
editorial playlist. The database is the state: a stint is open while its
`end_date` is NULL. Each run:

  - track in the playlist now, no open stint   -> new row (`end_date` NULL);
  - track in the playlist now, already open    -> nothing;
  - track with an open stint, gone now         -> `end_date = today`.

Safety rails against bad embed responses:
  - a playlist that fails to fetch, or returns nothing, is skipped;
  - a playlist whose tracklist is >= PARTIAL_RESPONSE_DROP tracks shorter than
    its current open-stint count is treated as a partial response: skipped, DB
    untouched, loud WARNING;
  - if more than half the editorials are skipped for any of those reasons, the
    run aborts without writing anything (circuit breaker);
  - the count of skipped playlists is emitted as a CloudWatch metric.
"""

import json
import logging
import sys
import time
from collections import defaultdict
from datetime import date

import requests
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel

from src.artists import split_artist_names
from src.consts import (
    EDITORIALS,
    HTTP_HEADERS,
    PARTIAL_RESPONSE_DROP,
    REQUEST_DELAY,
    SKIPPED_METRIC,
    Editorial,
)
from src.db import create_db_engine, db_config_from_env
from src.embed import PlaylistTrack, PlaylistUnavailable, fetch_playlist_tracklist
from src.models import EditorialPlaylist, EditorialPlaylistStorico

logger = logging.getLogger(__name__)

_OWNED_TABLES = [EditorialPlaylist.__table__, EditorialPlaylistStorico.__table__]


def diff_playlist(
    present_ids: set[str], open_ids: set[str]
) -> tuple[set[str], set[str], set[str]]:
    """Split the current tracklist against the open stints in the DB.

    Returns (to_open, to_close, to_keep):
      - to_open  : present now, no open stint   -> start a new stint;
      - to_close : had an open stint, gone now  -> close it;
      - to_keep  : present now and already open -> nothing to do.
    """
    return (
        present_ids - open_ids,
        open_ids - present_ids,
        present_ids & open_ids,
    )


def is_partial_response(present_count: int, open_count: int) -> bool:
    """True when today's tracklist is suspiciously short vs the open stints.

    `present_count` tracks came back; we currently have `open_count` open stints
    for that playlist. A drop of PARTIAL_RESPONSE_DROP or more is treated as a
    partial/broken response, not a real mass exit.
    """
    return open_count - present_count >= PARTIAL_RESPONSE_DROP


def _emit_metric(name: str, value: int) -> None:
    """One JSON line on stdout; a Terraform log-metric-filter turns it into a
    CloudWatch metric (terraform/alarms.tf)."""
    print(json.dumps({"metric": name, "value": value}), flush=True)


class EditorialsTracker:
    """Maintain the stint history of every track in the tracked editorials."""

    def __init__(self) -> None:
        self.engine = create_db_engine(db_config_from_env())
        self.session = requests.Session()
        self.session.headers.update(HTTP_HEADERS)

    # ------------------------------------------------------------------ #
    # setup                                                             #
    # ------------------------------------------------------------------ #
    def _ensure_tables(self) -> None:
        """Create the owned tables if missing (no migration tool here)."""
        try:
            SQLModel.metadata.create_all(
                self.engine, tables=_OWNED_TABLES, checkfirst=True
            )
        except Exception:
            logger.exception(
                "could not create the owned tables - have a DBA apply "
                "sql/schema.sql, then re-run"
            )
            raise

    def _upsert_registry(self, db: Session) -> None:
        """Make `editorial_playlists` match `EDITORIALS`."""
        stmt = pg_insert(EditorialPlaylist.__table__).values(
            [{"playlist_id": e.playlist_id, "playlist_name": e.name} for e in EDITORIALS]
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["playlist_id"],
            set_={"playlist_name": stmt.excluded.playlist_name},
        )
        db.execute(stmt)
        db.commit()

    def _open_stints(self, db: Session) -> dict[str, set[str]]:
        """Currently-open stints, straight from the DB: {playlist_id: {track_id}}."""
        open_by_playlist: dict[str, set[str]] = defaultdict(set)
        try:
            rows = db.execute(
                select(
                    EditorialPlaylistStorico.playlist_id,
                    EditorialPlaylistStorico.track_id,
                )
                .where(EditorialPlaylistStorico.end_date.is_(None))
                .distinct()
            ).all()
        except SQLAlchemyError:
            db.rollback()
            logger.warning(
                "could not read %s (not created yet?) - treating every track as new",
                EditorialPlaylistStorico.__tablename__,
            )
            return open_by_playlist
        for playlist_id, track_id in rows:
            open_by_playlist[playlist_id].add(track_id)
        return open_by_playlist

    # ------------------------------------------------------------------ #
    # run                                                               #
    # ------------------------------------------------------------------ #
    def run(self, dry_run: bool = False) -> None:
        today = date.today()
        if not dry_run:
            self._ensure_tables()

        # 1. fetch every playlist up front
        fetched: list[tuple[Editorial, list[PlaylistTrack]]] = []
        fetch_failed: list[str] = []
        for ed in EDITORIALS:
            try:
                tracklist = fetch_playlist_tracklist(ed.playlist_id, self.session)
            except PlaylistUnavailable:
                logger.warning(
                    "editorial %s (%s) still 404s after retries - skipping",
                    ed.name, ed.playlist_id,
                )
                fetch_failed.append(ed.name)
            except Exception:
                logger.exception("skipping editorial %s (%s)", ed.name, ed.playlist_id)
                fetch_failed.append(ed.name)
            else:
                if not tracklist:
                    logger.warning(
                        "editorial %s (%s) returned no tracks - skipping",
                        ed.name, ed.playlist_id,
                    )
                    fetch_failed.append(ed.name)
                else:
                    fetched.append((ed, tracklist))
                    logger.info("%s: %d tracks", ed.name, len(tracklist))
            time.sleep(REQUEST_DELAY)

        with Session(self.engine) as db:
            if not dry_run:
                self._upsert_registry(db)

            open_by_playlist = self._open_stints(db)

            # 2. per-playlist plan + partial-response check
            plans: dict[str, tuple[set[str], set[str], set[str]]] = {}
            partial: list[str] = []  # names of playlists with a suspicious response
            for ed, tracklist in fetched:
                present_ids = {pt.spotify_id for pt in tracklist}
                open_ids = open_by_playlist.get(ed.playlist_id, set())
                plans[ed.playlist_id] = diff_playlist(present_ids, open_ids)
                if is_partial_response(len(present_ids), len(open_ids)):
                    partial.append(ed.name)
                    logger.warning(
                        "%s: %d tracks vs %d open stints (>= %d fewer) - response "
                        "looks PARTIAL, not touching the DB for this playlist",
                        ed.name, len(present_ids), len(open_ids), PARTIAL_RESPONSE_DROP,
                    )

            skipped_total = len(fetch_failed) + len(partial)
            _emit_metric(SKIPPED_METRIC, skipped_total)

            # 3. circuit breaker: too many playlists unusable -> abort, write nothing
            if skipped_total > len(EDITORIALS) // 2:
                logger.error(
                    "circuit breaker: %d/%d editorials skipped this run "
                    "(fetch-failed: %s | partial: %s) - aborting without writing",
                    skipped_total, len(EDITORIALS),
                    ", ".join(fetch_failed) or "-", ", ".join(partial) or "-",
                )
                if not dry_run:
                    sys.exit(1)
                return

            # 4. apply per playlist: close the gone ones, insert the new stints
            partial_ids = {
                ed.playlist_id for ed, _ in fetched if ed.name in partial
            }
            opened = closed = 0
            for ed, tracklist in fetched:
                if ed.playlist_id in partial_ids:
                    continue
                to_open, to_close, to_keep = plans[ed.playlist_id]
                new_rows = self._rows_for_new_stints(ed, tracklist, to_open, today)
                opened += len(to_open)
                closed += len(to_close)

                if dry_run:
                    logger.info(
                        "%s: open %d new stint(s) (%d rows), close %d, keep %d",
                        ed.name, len(to_open), len(new_rows), len(to_close),
                        len(to_keep),
                    )
                    continue

                try:
                    if to_close:
                        db.execute(
                            update(EditorialPlaylistStorico)
                            .where(
                                EditorialPlaylistStorico.playlist_id == ed.playlist_id,
                                EditorialPlaylistStorico.track_id.in_(to_close),
                                EditorialPlaylistStorico.end_date.is_(None),
                            )
                            .values(end_date=today)
                        )
                    db.add_all(new_rows)
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("write failed for editorial %s", ed.playlist_id)
                    opened -= len(to_open)
                    closed -= len(to_close)
                    continue

            skipped_names = fetch_failed + [f"{n} (partial)" for n in partial]
            logger.info(
                "done: %s - fetched %d/%d playlists, opened %d, closed %d, "
                "skipped %d%s",
                today, len(fetched), len(EDITORIALS), opened, closed,
                skipped_total,
                f" [{', '.join(skipped_names)}]" if skipped_names else "",
            )

    # ------------------------------------------------------------------ #
    # helpers                                                           #
    # ------------------------------------------------------------------ #
    def _rows_for_new_stints(
        self,
        editorial: Editorial,
        tracklist: list[PlaylistTrack],
        to_open: set[str],
        today: date,
    ) -> list[EditorialPlaylistStorico]:
        """One row per (track, artist name) for the tracks starting a new stint.

        A track with no parseable artist string still yields a single row (with
        artist_name NULL) so the stint is recorded.
        """
        rows: list[EditorialPlaylistStorico] = []
        for pt in tracklist:
            if pt.spotify_id not in to_open:
                continue
            for name in split_artist_names(pt.artists) or [None]:
                rows.append(
                    EditorialPlaylistStorico(
                        playlist_id=editorial.playlist_id,
                        playlist_name=editorial.name,
                        track_name=pt.title or None,
                        track_id=pt.spotify_id,
                        artist_name=name,
                        start_date=today,
                        end_date=None,
                    )
                )
        return rows
