"""EditorialsTracker: the daily run.

The pipeline keeps one row per *stint* — a continuous period a track spent in an
editorial playlist. Which stints are currently open is held in a small JSON
state document (src/state.py), not inferred from the history table:

  - track in the playlist now, not in the state    -> new row (`end_date` NULL),
    artists resolved via src/artists.py; added to the state;
  - track in the playlist now and in the state      -> nothing in the DB; its
    `last_seen` in the state is moved to today;
  - track in the state but gone from the playlist   -> its open row gets
    `end_date = last_seen` (the last date it was there); removed from the state.

A playlist that fails to fetch (or returns nothing) is logged and skipped: its
state entries are left untouched, so nothing is closed by mistake. The DB
changes and the state file are written per playlist.
"""

import logging
import time
from datetime import date

import requests
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel

from src.artists import ArtistResolver, split_artist_names
from src.consts import EDITORIALS, HTTP_HEADERS, REQUEST_DELAY, Editorial
from src.db import create_db_engine, db_config_from_env
from src.embed import PlaylistTrack, PlaylistUnavailable, fetch_playlist_tracklist
from src.models import EditorialPlaylist, EditorialPlaylistStorico
from src.state import StateStore, empty_doc, open_stints

logger = logging.getLogger(__name__)

_OWNED_TABLES = [EditorialPlaylist.__table__, EditorialPlaylistStorico.__table__]


def diff_playlist(
    present_ids: set[str], open_ids: set[str]
) -> tuple[set[str], set[str], set[str]]:
    """Split the current tracklist against the open-stint state.

    Returns (to_open, to_close, to_keep):
      - to_open  : present now, no open stint      -> start a new stint;
      - to_close : had an open stint, gone now     -> close it;
      - to_keep  : present now and already open    -> just refresh last_seen.
    """
    return (
        present_ids - open_ids,
        open_ids - present_ids,
        present_ids & open_ids,
    )


class EditorialsTracker:
    """Maintain the stint history of every track in the tracked editorials."""

    def __init__(self, *, use_apify: bool = True) -> None:
        self.engine = create_db_engine(db_config_from_env())
        self.use_apify = use_apify
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

    def _reconstruct_state(self, db: Session) -> dict:
        """Rebuild the state document from the open rows in the DB.

        Used only when the state file is missing (first run, or it was lost):
        without this every open track would look new and get a duplicate row.
        """
        doc = empty_doc()
        try:
            rows = db.execute(
                select(
                    EditorialPlaylistStorico.playlist_id,
                    EditorialPlaylistStorico.track_id,
                    func.min(EditorialPlaylistStorico.start_date),
                )
                .where(EditorialPlaylistStorico.end_date.is_(None))
                .group_by(
                    EditorialPlaylistStorico.playlist_id,
                    EditorialPlaylistStorico.track_id,
                )
            ).all()
        except SQLAlchemyError:
            db.rollback()
            logger.warning(
                "could not read %s - starting from an empty state",
                EditorialPlaylistStorico.__tablename__,
            )
            return doc

        for playlist_id, track_id, start in rows:
            iso = start.isoformat()
            open_stints(doc, playlist_id)[track_id] = {"start": iso, "last_seen": iso}
        if rows:
            logger.warning("rebuilt state from %d open rows in the DB", len(rows))
        return doc

    # ------------------------------------------------------------------ #
    # run                                                               #
    # ------------------------------------------------------------------ #
    def run(self, dry_run: bool = False) -> None:
        today = date.today()
        if not dry_run:
            self._ensure_tables()

        # 1. fetch every playlist up front
        fetched: list[tuple[Editorial, list[PlaylistTrack]]] = []
        for ed in EDITORIALS:
            try:
                tracklist = fetch_playlist_tracklist(ed.playlist_id, self.session)
            except PlaylistUnavailable:
                logger.warning(
                    "editorial %s (%s) still 404s after retries - skipping",
                    ed.name, ed.playlist_id,
                )
            except Exception:
                logger.exception("skipping editorial %s (%s)", ed.name, ed.playlist_id)
            else:
                if not tracklist:
                    logger.warning(
                        "editorial %s (%s) returned no tracks - skipping (state "
                        "left untouched)", ed.name, ed.playlist_id,
                    )
                else:
                    fetched.append((ed, tracklist))
                    logger.info("%s: %d tracks", ed.name, len(tracklist))
            time.sleep(REQUEST_DELAY)

        store = StateStore()
        doc = store.load()

        with Session(self.engine) as db:
            if not dry_run:
                self._upsert_registry(db)
            if doc is None:
                logger.warning(
                    "no state file at %s - reconstructing from the DB", store.location
                )
                doc = self._reconstruct_state(db)

            # 2. plan per playlist, then resolve artist ids for the new tracks only
            plans: dict[str, tuple[set[str], set[str], set[str]]] = {}
            for ed, tracklist in fetched:
                present_ids = {pt.spotify_id for pt in tracklist}
                open_ids = set(open_stints(doc, ed.playlist_id))
                plans[ed.playlist_id] = diff_playlist(present_ids, open_ids)

            resolver = ArtistResolver(self.engine, use_apify=self.use_apify)
            resolver.load_db_map()

            need_apify: set[str] = set()
            for ed, tracklist in fetched:
                to_open, _, _ = plans[ed.playlist_id]
                for pt in tracklist:
                    if pt.spotify_id not in to_open:
                        continue
                    if any(
                        not resolver.is_known(n)
                        for n in split_artist_names(pt.artists)
                    ):
                        need_apify.add(pt.spotify_id)
            if need_apify:
                logger.info(
                    "%d new tracks need an Apify lookup for artist ids", len(need_apify)
                )
                resolver.enrich_via_apify(need_apify)

            # 3. apply per playlist: close, open, refresh last_seen, save state
            opened = closed = 0
            for ed, tracklist in fetched:
                to_open, to_close, to_keep = plans[ed.playlist_id]
                pl_state = open_stints(doc, ed.playlist_id)
                new_rows = self._rows_for_new_stints(
                    ed, tracklist, to_open, resolver, today
                )
                opened += len(to_open)
                closed += len(to_close)

                if dry_run:
                    logger.info(
                        "%s: open %d new stint(s) (%d rows), close %d, keep %d",
                        ed.name, len(to_open), len(new_rows), len(to_close),
                        len(to_keep),
                    )
                    for r in new_rows:
                        logger.info(
                            "  open: %s - %s  track=%s artist=%s",
                            r.track_name, r.artist_name, r.track_id, r.artist_id,
                        )
                    continue

                try:
                    for track_id in to_close:
                        last_seen = date.fromisoformat(pl_state[track_id]["last_seen"])
                        db.execute(
                            update(EditorialPlaylistStorico)
                            .where(
                                EditorialPlaylistStorico.playlist_id == ed.playlist_id,
                                EditorialPlaylistStorico.track_id == track_id,
                                EditorialPlaylistStorico.end_date.is_(None),
                            )
                            .values(end_date=last_seen)
                        )
                    db.add_all(new_rows)
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception("write failed for editorial %s", ed.playlist_id)
                    opened -= len(to_open)
                    closed -= len(to_close)
                    continue

                for track_id in to_close:
                    pl_state.pop(track_id, None)
                for track_id in to_keep:
                    pl_state[track_id]["last_seen"] = today.isoformat()
                for pt in tracklist:
                    if pt.spotify_id in to_open:
                        pl_state[pt.spotify_id] = {
                            "start": today.isoformat(),
                            "last_seen": today.isoformat(),
                        }
                store.save(doc)

            logger.info(
                "done: %s - opened %d, closed %d, across %d editorials",
                today, opened, closed, len(fetched),
            )

    # ------------------------------------------------------------------ #
    # helpers                                                           #
    # ------------------------------------------------------------------ #
    def _rows_for_new_stints(
        self,
        editorial: Editorial,
        tracklist: list[PlaylistTrack],
        to_open: set[str],
        resolver: ArtistResolver,
        today: date,
    ) -> list[EditorialPlaylistStorico]:
        """One row per (track, artist) for the tracks starting a new stint.

        A track with no parseable artist string still yields a single row (with
        artist_name and artist_id NULL) so the stint is recorded.
        """
        rows: list[EditorialPlaylistStorico] = []
        for pt in tracklist:
            if pt.spotify_id not in to_open:
                continue
            names = split_artist_names(pt.artists) or [None]
            for name in names:
                artist_id = resolver.resolve(pt.spotify_id, name) if name else None
                rows.append(
                    EditorialPlaylistStorico(
                        playlist_id=editorial.playlist_id,
                        playlist_name=editorial.name,
                        track_name=pt.title or None,
                        track_id=pt.spotify_id,
                        artist_name=name,
                        artist_id=artist_id,
                        start_date=today,
                        end_date=None,
                    )
                )
        return rows
