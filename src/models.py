"""SQLModel tables for the editorials_playlist pipeline.

Owned by this pipeline (created at runtime with `metadata.create_all(...,
checkfirst=True)` — no migration tool in this repo):

- `EditorialPlaylist` — registry of the tracked playlists (id + name). Mirrors
  `EDITORIALS` in src/consts.py; re-upserted on every run.
- `EditorialPlaylistStorico` — stint history and state in one: one row per
  (playlist, track, artist name, stint); `end_date IS NULL` marks an open stint.
"""

from datetime import date

from sqlmodel import Field, SQLModel

from src.consts import DB_SCHEMA


class EditorialPlaylist(SQLModel, table=True):
    """Registry row: one tracked editorial playlist."""

    __tablename__ = "editorial_playlists"
    __table_args__ = {"schema": DB_SCHEMA}

    playlist_id: str = Field(primary_key=True)
    playlist_name: str


class EditorialPlaylistStorico(SQLModel, table=True):
    """One stint of a track in an editorial playlist, one row per credited artist.

    A "stint" is a continuous period the track was in the playlist:
    - `start_date` — first run that saw the track in the playlist (this stint);
    - `end_date`   — NULL while the track is still in the playlist; set to the
      run date that first found it gone.

    This table is the state: a stint is open while `end_date IS NULL`. A track
    that leaves and later returns gets a new row.
    """

    __tablename__ = "editorial_playlists_storico"
    __table_args__ = {"schema": DB_SCHEMA}

    id: int | None = Field(default=None, primary_key=True)

    playlist_id: str = Field(
        foreign_key=f"{DB_SCHEMA}.editorial_playlists.playlist_id",
        index=True,
    )
    playlist_name: str | None = Field(default=None)
    track_name: str | None = Field(default=None)
    track_id: str = Field(index=True)
    artist_name: str | None = Field(default=None)  # one credited artist (embed subtitle, split)
    start_date: date = Field(index=True)
    end_date: date | None = Field(default=None, index=True)
