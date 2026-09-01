# editorials_playlist

Tracks **every track and every artist** in the Italian Spotify **editorial
playlists** we follow. Instead of a row per day, it keeps one row per *stint* —
a continuous period a track spent in a playlist: `start_date` when it enters,
`end_date` NULL while it's in, filled with the last date it was there once it
leaves. Feeds hype metrics: which tracks/artists are in the editorials, in how
many, and for how long.

Which stints are open is held in a small JSON state file
(`editorial_playlist_state/open_stints.json` on S3, or a local file in dev), not
inferred from the history table.

Full design: [Documentazione editorials_playlist.md](Documentazione%20editorials_playlist.md).

## Commands

```bash
uv sync                              # install deps into .venv
uv run main.py --dry-run             # fetch + log what would be written
uv run main.py --dry-run --no-apify  # ... and skip the Apify artist-id lookup
uv run main.py                       # apply today's stint changes to the DB
uv run python -m pytest              # unit tests (embed parsing + artist resolution)
```

Required env vars (loaded from `.env` via `load_dotenv()`): `DB_HOST`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_PORT` (default `5432`), `SPOTIFY_API_KEY` (the
Apify token — same one ASP's spotify pipeline uses; leave unset to run with
`--no-apify` behaviour), and `S3_BUCKET_NAME` + `AWS_REGION` for the state file
(unset → local `editorial_state.json`).

## How it works

1. `src/consts.py::EDITORIALS` — the fixed list of tracked playlists. Every run
   upserts it into `social_golden_data.editorial_playlists` (`playlist_id`,
   `playlist_name`).
2. For each, `src/embed.py` fetches the public embed page
   (`open.spotify.com/embed/playlist/{id}`) and parses its `__NEXT_DATA__` JSON
   into a `list[PlaylistTrack]` (track id, title, artist string). The endpoint
   404s intermittently for healthy playlists, so the fetch retries on that too.
3. `src/processor.py` loads the state file (`src/state.py`) and, for each
   playlist, diffs the current tracklist against the open stints in it:
   - track present, **not** in the state → new row in
     `social_golden_data.editorial_playlists_storico` (`end_date` NULL); added
     to the state with `start`/`last_seen` = today;
   - track present **and** in the state → nothing in the DB; its `last_seen` in
     the state moves to today;
   - track in the state but **gone** from the playlist → its open row gets
     `end_date = last_seen`; removed from the state.
   A playlist that fails to fetch (or returns nothing) is skipped and its state
   entries are left alone, so nothing is closed by mistake.
4. Only tracks starting a new stint need an artist id.
   `src/artists.py::ArtistResolver` resolves each artist *name*:
   `social_golden_data.spotify_track_artists` (normalized name) first, then one
   batched Apify call (actor `beatanalytics/spotify-play-count-scraper`,
   `/track/{id}` URLs) for the rest. Unresolved → `artist_id` stays `NULL`.
5. Read-time views in `sql/views.sql`: who's currently in each editorial
   (`vw_editorial_current` = `end_date IS NULL`), per-track / per-artist counts,
   and stint tenure.

DDL for both tables: `sql/schema.sql` (also created at runtime with
`checkfirst=True` when the role has DDL rights). If the state file is missing,
the run rebuilds it from the open (`end_date IS NULL`) rows in the DB.

## Deploy

Docker image on ECS Fargate, run daily at 00:00 UTC by EventBridge Scheduler,
image pushed to ECR by `.github/workflows/deploy-ecr.yml` on push to `main`.
Infra in `terraform/` (mirror of `song_resolver_tracker`). Set
`github_oidc_provider_arn` (the account already has the provider),
`secrets_manager_arn` (holds `DB_*` and `SPOTIFY_API_KEY`) and `state_s3_bucket`
(bucket for the state file; the task role gets `s3:GetObject`/`s3:PutObject` on
`editorial_playlist_state/*` there).
