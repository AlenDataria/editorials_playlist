-- The single table this pipeline writes to.
-- The pipeline also tries to create it at runtime (SQLModel, checkfirst=True),
-- but that needs DDL rights on the schema; run this once as a DBA if the app
-- role can't create tables.

CREATE TABLE IF NOT EXISTS social_golden_data.editorial_playlist_entries (
    playlist_id    text        NOT NULL,
    spotify_id     text        NOT NULL,          -- = social_golden_data.spotify_tracks.spotify_id
    snapshot_date  date        NOT NULL,          -- date of the run
    playlist_name  text,                          -- editorial name (from src/consts.py::EDITORIALS)
    track_name     text,                          -- from our data
    artist_name    text,                          -- our artists, joined with ', '
    album_name     text,                          -- from our data (the embed has no album)
    position       integer     NOT NULL,          -- 1-based rank in the playlist
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (playlist_id, spotify_id, snapshot_date)
);

-- Common access path: "everything for track X over time".
CREATE INDEX IF NOT EXISTS ix_epe_spotify_id_date
    ON social_golden_data.editorial_playlist_entries (spotify_id, snapshot_date);
