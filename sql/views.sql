-- Read-time views over social_golden_data.editorial_playlist_entries.
-- Apply once after the first pipeline run has created the table.
-- See "Documentazione editorials_playlist.md", Step 4.

-- a) How many editorials a track is in on a given day, and which ones.
CREATE OR REPLACE VIEW social_golden_data.vw_track_editorial_count AS
SELECT
    spotify_id,
    snapshot_date,
    count(*)                                        AS editorial_count,
    array_agg(playlist_name ORDER BY playlist_name) AS playlists
FROM social_golden_data.editorial_playlist_entries
GROUP BY spotify_id, snapshot_date;


-- b) Tenure: first/last day seen and total days present, per (track, editorial).
--    still_in = last_seen is the most recent snapshot in the table.
CREATE OR REPLACE VIEW social_golden_data.vw_track_editorial_tenure AS
SELECT
    e.spotify_id,
    e.playlist_id,
    e.playlist_name,
    min(e.snapshot_date) AS first_seen,
    max(e.snapshot_date) AS last_seen,
    count(*)             AS days_present,
    max(e.snapshot_date) = (SELECT max(snapshot_date)
                            FROM social_golden_data.editorial_playlist_entries)
                        AS still_in
FROM social_golden_data.editorial_playlist_entries e
GROUP BY e.spotify_id, e.playlist_id, e.playlist_name;


-- c) Position over time with rise/fall vs the previous snapshot.
--    delta > 0 means the track moved up (towards #1).
CREATE OR REPLACE VIEW social_golden_data.vw_track_position_trend AS
SELECT
    spotify_id,
    playlist_id,
    playlist_name,
    snapshot_date,
    position,
    lag(position) OVER w             AS prev_position,
    lag(position) OVER w - position  AS delta
FROM social_golden_data.editorial_playlist_entries
WINDOW w AS (PARTITION BY spotify_id, playlist_id ORDER BY snapshot_date);

-- d) Viral road: NOT implemented yet (see Step 4). When the editorial->stage
--    mapping is agreed, add a vw_track_viral_road view here over this same table.
