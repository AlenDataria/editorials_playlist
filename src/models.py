"""SQLModel tables for the editorials_playlist pipeline.

Owned by this pipeline (created at runtime with `metadata.create_all(...,
checkfirst=True)` — no migration tool in this repo):

- `EditorialPlaylist` — registry of the tracked playlists (id + name). Mirrors
  `EDITORIALS` in src/consts.py; re-upserted on every run.
- `EditorialPlaylistStorico` — stint history: one row per
  (playlist, track, artist, stint), with a `start_date` / `end_date` window.

`SpotifyTrackArtists` mirrors the shared source table and is read-only: it is
the first place we look for an `artist_id` given an artist name.
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
      last date it was present once a run finds it gone.

    Which stints are open is tracked out-of-band in the state document
    (src/state.py), not inferred from this table. A track that leaves and later
    returns gets a new row. `artist_id` is NULL when it could not be resolved
    from our data or Apify.
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
    artist_name: str | None = Field(default=None)
    artist_id: str | None = Field(default=None, index=True)
    start_date: date = Field(index=True)
    end_date: date | None = Field(default=None, index=True)


class SpotifyTrackArtists(SQLModel, table=True):
    """Read-only mirror of the shared `spotify_track_artists` source table."""

    __tablename__ = "spotify_track_artists"
    __table_args__ = {"schema": DB_SCHEMA}

    spotify_track_id: str = Field(primary_key=True)
    artist_id: str = Field(primary_key=True)
    artist_name: str | None = Field(default=None)
