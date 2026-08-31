# editorials_playlist

Tracks which of our Spotify tracks appear in the Italian Spotify **editorial
playlists**, and at what position, one snapshot per day. Feeds hype metrics:
how many editorials a song is in, for how long, at what position and trend.

Full design: [Documentazione editorials_playlist.md](Documentazione%20editorials_playlist.md).

## Commands

```bash
uv sync                       # install deps into .venv
uv run main.py --dry-run      # fetch + log matches, write nothing
uv run main.py                # write today's snapshot rows
uv run python -m pytest       # unit tests (embed parsing + matching)
```

Required env vars (loaded from `.env` via `load_dotenv()`): `DB_HOST`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_PORT` (default `5432`).

## How it works

1. `src/consts.py::EDITORIALS` — the fixed list of 16 tracked playlists.
2. For each, `src/embed.py` fetches the public embed page
   (`open.spotify.com/embed/playlist/{id}`) and parses its `__NEXT_DATA__` JSON
   into an ordered `list[PlaylistTrack]` (position, spotify_id, title, artists).
3. `src/processor.py` loads our campaign-active `spotify_tracks` and matches:
   exact `spotify_id` first, fuzzy title+artist (`src/matching.py`) as fallback.
4. One row per `(playlist_id, spotify_id, snapshot_date)` is written to
   `social_golden_data.editorial_playlist_entries` (created on first run).
5. Read-time views in `sql/views.sql` derive the counts / tenure / position
   trend. "Viral road" is documented but not implemented yet (see Step 4).

## Deploy

Docker image on ECS Fargate, run daily at 00:00 UTC by EventBridge Scheduler,
image pushed to ECR by `.github/workflows/deploy-ecr.yml` on push to `main`.
Infra in `terraform/` (mirror of `song_resolver_tracker`). Set
`github_oidc_provider_arn` (the account already has the provider) and
`secrets_manager_arn` (DB_* only).
