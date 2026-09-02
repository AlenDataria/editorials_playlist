# editorials_playlist

Tracks **every track** in the Italian Spotify **editorial playlists** we follow.
Instead of a row per day, it keeps one row per *stint* — a continuous period a
track spent in a playlist: `start_date` when it enters, `end_date` NULL while
it's in, filled once a run finds it gone. One row per credited artist name.
Feeds hype metrics: which tracks are in the editorials, in how many, for how long.

The database is the state: a stint is open while `end_date IS NULL`. No extra
store — each run reads the open rows and diffs the current tracklist against
them.

Full design: [Documentazione editorials_playlist.md](Documentazione%20editorials_playlist.md).

## Commands

```bash
uv sync                     # install deps into .venv
uv run main.py --dry-run    # fetch + log what would be written, no DB writes
uv run main.py              # apply today's stint changes to the DB
uv run python -m pytest     # unit tests
```

Required env vars (loaded from `.env` via `load_dotenv()`): `DB_HOST`, `DB_NAME`,
`DB_USER`, `DB_PASSWORD`, `DB_PORT` (default `5432`).

## How it works

1. `src/consts.py::EDITORIALS` — the fixed list of tracked playlists. Every run
   upserts it into `social_golden_data.editorial_playlists` (`playlist_id`,
   `playlist_name`).
2. For each, `src/embed.py` fetches the public embed page
   (`open.spotify.com/embed/playlist/{id}`) and parses its `__NEXT_DATA__` JSON
   into a `list[PlaylistTrack]` (track id, title, artist string). The endpoint
   404s intermittently for healthy playlists, so the fetch retries on that too.
3. `src/processor.py` reads the open stints from the DB
   (`SELECT playlist_id, track_id FROM social_golden_data.editorial_playlists_storico
   WHERE end_date IS NULL`) and, for each playlist, diffs the current tracklist
   against them:
   - track present, **no** open stint → new row(s), one per artist name
     (`start_date = today`, `end_date` NULL);
   - track present **and** already open → nothing;
   - track with an open stint, **gone** from the playlist → `end_date = today`.
4. Read-time views in `sql/views.sql`: who's currently in each editorial
   (`vw_editorial_current` = `end_date IS NULL`), per-track / per-artist-name
   counts, and stint tenure.

DDL for both tables: `sql/schema.sql` (also created at runtime with
`checkfirst=True` when the role has DDL rights).

## Safety rails against bad embed responses

- **Empty / failed fetch** → the playlist is skipped, its open stints untouched.
- **Partial response** — the fetched tracklist has `PARTIAL_RESPONSE_DROP` (20)
  or more *fewer* tracks than that playlist's current open-stint count → treated
  as broken: the playlist is skipped, DB untouched, `WARNING` logged. A genuine
  mass turnover (New Music Friday) has a normal-sized tracklist, so it does not
  trip this. A playlist that legitimately shrinks a lot keeps warning every run
  until someone reconciles it by hand.
- **Circuit breaker** — if more than half the editorials are skipped in a run,
  it aborts with `exit(1)` (the ECS task fails) without writing anything.
- **Metric** — every run prints `{"metric": "editorials_playlists_skipped",
  "value": N}` to stdout; `terraform/alarms.tf` turns it into a CloudWatch
  metric with an alarm on `> 0`.

## Deploy

Docker image on ECS Fargate, run daily at 00:00 UTC by EventBridge Scheduler,
image pushed to ECR by `.github/workflows/deploy-ecr.yml` on push to `main`.
Infra in `terraform/` (mirror of `song_resolver_tracker`). Set
`github_oidc_provider_arn` (the account already has the provider),
`secrets_manager_arn` (holds `DB_*`) and, optionally, `alarm_sns_topic_arn` for
the skipped-playlists alarm.
