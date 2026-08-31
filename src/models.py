"""SQLModel tables and the SourceTrack dataclass.

- `EditorialPlaylistEntry` is owned by this pipeline: one row per
  (playlist, our track, day). It is created at runtime with
  `__table__.create(..., checkfirst=True)` — there is no migration tool in this
  repo, same pattern as song_resolver_tracker's `tiktok_unresolved_tracks`.
- `SpotifyTrack` / `SpotifyTrackArtists` mirror the shared source tables and are
  used read-only, exactly as in
  song_resolver_tracker/src/platforms/tiktok/models.py.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlmodel import Field, SQLModel

from src.consts import DB_SCHEMA


class EditorialPlaylistEntry(SQLModel, table=True):
    """A daily snapshot: this track was in this editorial, at this position."""

    __tablename__ = "editorial_playlist_entries"
    __table_args__ = {"schema": DB_SCHEMA}

    playlist_id: str = Field(primary_key=True)
    spotify_id: str = Field(primary_key=True)  # = spotify_tracks.spotify_id
    snapshot_date: date = Field(primary_key=True)

    playlist_name: str | None = Field(default=None)
    track_name: str | None = Field(default=None)      # from our data
    artist_name: str | None = Field(default=None)     # our artists, joined with ", "
    album_name: str | None = Field(default=None)      # from our data (embed has no album)
    position: int = Field()                           # 1-based rank in the playlist
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class SpotifyTrack(SQLModel, table=True):
    """Read-only mirror of the shared `spotify_tracks` source table."""

    __tablename__ = "spotify_tracks"
    __table_args__ = {"schema": DB_SCHEMA}

    spotify_id: str = Field(primary_key=True)
    track_name: str | None = Field(default=None)
    album_id: str | None = Field(default=None)
    album_name: str | None = Field(default=None)
    release_type: str | None = Field(default=None)
    release_date: date | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Campaign toggle: only tracks with active != false are tracked.
    active: bool | None = Field(default=True)


class SpotifyTrackArtists(SQLModel, table=True):
    """Read-only mirror of the shared `spotify_track_artists` source table."""

    __tablename__ = "spotify_track_artists"
    __table_args__ = {"schema": DB_SCHEMA}

    spotify_track_id: str = Field(primary_key=True)
    artist_id: str = Field(primary_key=True)
    artist_name: str | None = Field(default=None)


@dataclass
class SourceTrack:
    """One of our Spotify tracks, with all of its artists kept together."""

    spotify_id: str
    track_name: str | None
    album_name: str | None
    artist_names: list[str] = field(default_factory=list)
