-- Read-time views over social_golden_data.editorial_playlists_storico.
-- Apply once after the first pipeline run has created the tables.

-- Tracks currently in a playlist: their stint is still open (end_date IS NULL).
CREATE OR REPLACE VIEW social_golden_data.vw_editorial_current AS
SELECT *
FROM social_golden_data.editorial_playlists_storico
WHERE end_date IS NULL;


-- a) How many editorials a track is currently in, and which ones.
CREATE OR REPLACE VIEW social_golden_data.vw_track_editorial_count AS
SELECT
    track_id,
    max(track_name)                                     AS track_name,
    count(DISTINCT playlist_id)                         AS editorial_count,
    array_agg(DISTINCT playlist_name ORDER BY playlist_name) AS playlists
FROM social_golden_data.vw_editorial_current
GROUP BY track_id;


-- b) How many editorials an artist is currently in (any of their tracks).
CREATE OR REPLACE VIEW social_golden_data.vw_artist_editorial_count AS
SELECT
    artist_id,
    max(artist_name)                                    AS artist_name,
    count(DISTINCT playlist_id)                         AS editorial_count,
    count(DISTINCT track_id)                            AS track_count,
    array_agg(DISTINCT playlist_name ORDER BY playlist_name) AS playlists
FROM social_golden_data.vw_editorial_current
WHERE artist_id IS NOT NULL
GROUP BY artist_id;


-- c) Tenure: every stint of a track in an editorial, with its length and
--    whether it is still open. days_present counts through today for open ones.
CREATE OR REPLACE VIEW social_golden_data.vw_track_editorial_tenure AS
SELECT
    track_id,
    max(track_name)                                        AS track_name,
    playlist_id,
    max(playlist_name)                                     AS playlist_name,
    start_date,
    end_date,
    (COALESCE(end_date, CURRENT_DATE) - start_date) + 1    AS days_present,
    end_date IS NULL                                       AS still_in
FROM social_golden_data.editorial_playlists_storico
GROUP BY track_id, playlist_id, start_date, end_date;
