# Documentazione editorials_playlist

Pipeline che tiene aggiornata la storia di **tutte le tracce e tutti gli
artisti** presenti nelle playlist editoriali di Spotify Italia che seguiamo. Non
una riga al giorno, ma **una riga per _stint_** — un periodo continuo di
permanenza di una traccia in un editoriale — con `start_date` ed `end_date`. Da
qui si ricava in quanti editoriali è una traccia/un artista, da quando e per
quanto.

Stesso impianto infrastrutturale di `song_resolver_tracker`: Docker + ECS Fargate
+ EventBridge (run giornaliero) + deploy via GitHub OIDC + Terraform.

---

## Step 1 — Cosa fa la pipeline

Una volta al giorno (`uv run main.py`):

1. **Registro playlist.** Upsert di `EDITORIALS` (`src/consts.py`) nella tabella
   `social_golden_data.editorial_playlists` (`playlist_id`, `playlist_name`).
   L'elenco vive nel codice; la tabella è la copia leggibile sul DB e il target
   della foreign key dello storico.
2. **Fetch.** Per ogni editoriale scarica la tracklist corrente dall'**endpoint
   embed pubblico** `https://open.spotify.com/embed/playlist/{ID}` (parse del
   blob `__NEXT_DATA__` nell'HTML) e ne ricava `(track_id, titolo,
   stringa_artisti)`.
3. **Diff sugli stint.** Si carica il **file di stato** (`src/state.py`) — un
   JSON unico che elenca, per playlist, le tracce con stint aperto e per ognuna
   `start` e `last_seen`. Sta su S3 (`editorial_playlist_state/open_stints.json`,
   bucket da `S3_BUCKET_NAME`) o, se il bucket non è settato, su un file locale.
   Per ogni editoriale scaricato si confrontano le tracce presenti ora con lo
   stato:
   - traccia presente **non** nello stato → **nuovo stint**: riga nello storico
     con `start_date = oggi`, `end_date = NULL`; aggiunta allo stato;
   - traccia presente **già** nello stato → niente sul DB; nello stato il suo
     `last_seen` va a oggi;
   - traccia nello stato ma **non più presente** → la riga aperta prende
     `end_date = last_seen` (l'ultima data in cui c'era); tolta dallo stato.
   Una playlist che fallisce il fetch (404 dopo i retry, errore, tracklist vuota)
   viene saltata: le sue voci nello stato **non** si toccano.
   Se il file di stato manca del tutto (primo run, o perso), viene ricostruito
   dalle righe aperte (`end_date IS NULL`) del DB.
4. **Artist id** (solo per le tracce che aprono un nuovo stint). L'embed dà il
   nome degli artisti ma non l'id. Per ogni nome:
   - **primario**: lookup in `social_golden_data.spotify_track_artists` per nome
     normalizzato (qualsiasi traccia su cui quell'artista è già comparso);
   - **fallback**: una chiamata Apify in batch (attore
     `beatanalytics/spotify-play-count-scraper`, URL `/track/{id}`, batch da 100)
     per le sole tracce nuove con almeno un artista non risolto; si legge
     `item["artists"]` = lista `{id, name}`. Precedenza ai crediti per-traccia di
     Apify, poi match per contenimento sul nome, poi le mappe globali.
   - non risolto → `artist_id` resta `NULL`, la riga si scrive lo stesso.
5. **Scrittura.** Per editoriale: `UPDATE end_date` per le chiusure + nuove righe
   (una per `(traccia, artista)`), commit, poi `save` del file di stato. Re-run
   nello stesso giorno = no-op (tutte le tracce già nello stato → solo `last_seen`
   riaggiornato a oggi).

> **Limite noto.** Se una traccia sparisce dall'embed per un solo giro (glitch,
> troncamento a 100) e poi ricompare, viene chiusa e poi riaperta come nuovo
> stint: nello storico compaiono due periodi con un buco di un giorno. È un
> rischio accettato; si può ricucire lato SQL a valle se diventa ricorrente.

### Perché l'endpoint embed e non l'API ufficiale
L'API ufficiale di Spotify restituisce **404** sugli editoriali (`37i9…`) per le
app in *development mode*, e il token anonimo del web player è stato bloccato.
L'endpoint embed è pubblico e senza auth. Limiti noti: (1) ritorna **max ~100
tracce** per playlist — una più lunga viene troncata in silenzio (il codice
logga un warning se la lista raggiunge il cap); (2) **non espone l'id
dell'artista** né il nome dell'album per traccia; (3) **404 intermittenti** su
playlist sanissime — il fetch fa retry con backoff anche su questo caso
(`PlaylistUnavailable` è ritentabile). Nota: l'embed non dà una posizione; la
pipeline non traccia più la posizione in classifica.

---

## Step 2 — Editoriali tracciati

Elenco fisso in `EDITORIALS` (`src/consts.py`), dataclass
`Editorial(playlist_id, name)`. EQUAL Italia esclusa.

| Playlist | playlist_id |
|---|---|
| Top 50 - Italia | `37i9dQZEVXbIQnj7RRhdSX` |
| Alta Rotazione | `37i9dQZF1DX01NP73ErE8b` |
| Hot Hits Italia | `37i9dQZF1DX6wfQutivYYr` |
| Hit Italiane | `37i9dQZF1DXcuVttLeQxkh` |
| New Music Friday Italia | `37i9dQZF1DWVKDF4ycOESi` |
| Novita Rap Italiano | `37i9dQZF1DX1OQlaot30zi` |
| Novita Indie Italiano | `37i9dQZF1DX6O5gXioqvYB` |
| nuovo pop Italia | `37i9dQZF1DX2c7QgpQBJFr` |
| GENERAZIONE Z | `37i9dQZF1DWYCIYGXn56uz` |
| sanguegiovane | `37i9dQZF1DWW9tK1GiTdMf` |
| anima R&B | `37i9dQZF1DWZuIX5Q3yUjF` |
| Hit Rap Italiane | `37i9dQZF1DWSxF6XNtQ9Rg` |
| Fresh Finds Italia | `37i9dQZF1DX0KBgD4Jf5tY` |
| RADAR Italia | `37i9dQZF1DWVjDgOMO8jZl` |
| Raptopia | `37i9dQZF1DWUQru3jd69v5` |

Rispetto alla versione precedente: **aggiunta** Raptopia; **rimosse** "Viral 50 -
Italia" (non servita via embed) e "Big Italiani" (playlist di status, fuori dal
segnale).

---

## Step 3 — Implementazione tecnica

### Struttura del repo

```
main.py                       # load_dotenv → parse_args → EditorialsTracker(...).run()
pyproject.toml                # deps: sqlmodel, psycopg2-binary, requests, python-dotenv, apify-client, boto3
Dockerfile                    # python:3.13-slim + uv sync --frozen; CMD = uv run main.py
terraform/                    # ECR, ECS cluster/task, ruoli IAM, 1 EventBridge schedule giornaliero
src/
  cli.py        # argparse: --dry-run, --no-apify, --log-level
  consts.py     # DB_SCHEMA, EMBED_URL, HTTP_HEADERS, REQUEST_*, RETRY_*, Apify consts, STATE_*, EDITORIALS
  db.py         # create_db_engine + retry_on_error + db_config_from_env
  models.py     # SQLModel: EditorialPlaylist, EditorialPlaylistStorico (owned) + SpotifyTrackArtists (read-only)
  embed.py      # fetch_playlist_tracklist / parse_tracklist → list[PlaylistTrack]
  artists.py    # normalize, split_artist_names, ArtistResolver (DB map + batched Apify fallback)
  state.py      # StateStore (S3 o file locale) + helper sul documento di stato
  processor.py  # EditorialsTracker: fetch → diff vs stato → apri / chiudi stint
sql/
  schema.sql    # DDL delle due tabelle
  views.sql     # viste read-time (chi è dentro ora, conteggi per traccia/artista, tenure)
tests/
  test_embed.py           # parsing __NEXT_DATA__ da fixture HTML
  test_artists.py         # normalize / split / ArtistResolver.resolve (no DB, no rete)
  test_state.py           # StateStore in modalità file locale (round-trip)
  test_processor_plan.py  # diff_playlist: apri / chiudi / mantieni
  test_editorials_live.py / test_editorials_order_live.py  # check di rete, solo con RUN_LIVE_TESTS=1
```

### Tabelle — `social_golden_data`

Di proprietà della pipeline, create a runtime con
`SQLModel.metadata.create_all(..., checkfirst=True)`; DDL a mano in
`sql/schema.sql` se il ruolo app non ha i permessi.

**`editorial_playlists`** — registro.

| colonna | tipo | note |
|---|---|---|
| `playlist_id` | text | PK |
| `playlist_name` | text | da `EDITORIALS` |

**`editorial_playlists_storico`** — uno stint per riga (una riga per artista).

| colonna | tipo | note |
|---|---|---|
| `id` | bigint identity | PK surrogata |
| `playlist_id` | text | FK → `editorial_playlists.playlist_id` |
| `playlist_name` | text | denormalizzato, comodo per le viste |
| `track_name` | text | titolo lato playlist |
| `track_id` | text | id Spotify della traccia (dall'embed) |
| `artist_name` | text | un artista accreditato (split della stringa embed) |
| `artist_id` | text | risolto da nostri dati o Apify; `NULL` se ignoto |
| `start_date` | date | primo run che ha visto la traccia in questo stint |
| `end_date` | date NULL | `NULL` finché la traccia è in playlist; alla chiusura = ultima data presente (`last_seen`) |

Grana: **una riga per (playlist, traccia, artista, stint)**. Quali stint sono
aperti lo dice il file di stato (`src/state.py`), non lo storico: "traccia dentro
adesso" = righe con `end_date IS NULL` (vista `vw_editorial_current`). Rientro
dopo un'uscita = nuova riga. Re-run nello stesso giorno = no-op.

**File di stato** (`open_stints.json`, S3 o locale):

```json
{
  "updated_at": "2026-09-01T00:00:00+00:00",
  "playlists": {
    "<playlist_id>": {
      "<track_id>": {"start": "2026-08-15", "last_seen": "2026-09-01"}
    }
  }
}
```

### `embed.py` — scraping

`fetch_playlist_tracklist(playlist_id, session)` fa GET sull'embed (con
`@retry_on_error`, backoff esponenziale su
`RequestException`/`EmbedParseError`/`PlaylistUnavailable`), poi
`parse_tracklist(html)`:
- estrae `<script id="__NEXT_DATA__">` con una regex;
- naviga `props.pageProps.state.data.entity.trackList`;
- per ogni elemento `entityType == "track"` con `uri` `spotify:track:` crea un
  `PlaylistTrack(position, spotify_id, title, artists)` — `spotify_id` =
  `uri.split(":")[-1]`, `title` = `title`, `artists` = `subtitle` (stringa con i
  featuring concatenati, es. `"Angelina Mango, Marco Mengoni"`). `position` (indice
  1-based) è ancora nel dataclass ma la pipeline non lo usa;
- se `len(trackList) >= 100` logga un warning "possibile troncamento";
- se `pageProps.state is None` o `status == 404` alza `PlaylistUnavailable`
  (ritentabile — l'embed lo fa a intermittenza).

### `state.py` — file di stato degli stint aperti

- `StateStore` — `load() -> dict | None` e `save(dict)`. Se `S3_BUCKET_NAME` è
  settato usa S3 (`boto3`, key `STATE_S3_KEY`, region `AWS_REGION`), altrimenti
  un file locale (`STATE_LOCAL_PATH`, override con `EDITORIAL_STATE_LOCAL_PATH`);
- `open_stints(doc, playlist_id)` → il dict `{track_id: {start, last_seen}}` di
  quella playlist (creato se assente);
- `empty_doc()` → `{"playlists": {}}`.

### `artists.py` — da nome ad `artist_id`

- `normalize(s)` → `(s or "").strip().casefold()`;
- `split_artist_names(subtitle)` → split su `","` con strip (il caso raro di un
  nome che contiene una virgola, es. "Tyler, The Creator", viene spezzato —
  accettato);
- `ArtistResolver(engine, use_apify=…)`:
  - `load_db_map()` — `SELECT DISTINCT artist_name, artist_id FROM
    spotify_track_artists` → `{nome_normalizzato: artist_id}`;
  - `is_known(name)` — usato dal processor per raccogliere le tracce che servono
    ad Apify;
  - `enrich_via_apify(track_ids)` — una chiamata all'attore ogni
    `APIFY_BATCH_SIZE` (100) tracce; popola `{track_id: {nome: id}}` e una mappa
    nome→id globale. Se manca `SPOTIFY_API_KEY` o `apify-client`, logga un
    warning e prosegue (artist_id resta `NULL`);
  - `resolve(track_id, name)` — crediti Apify per-traccia → contenimento sul
    nome nei crediti di quella traccia → mappa nostri dati → mappa Apify globale
    → `None`.

### `processor.py` — orchestrazione

`diff_playlist(present_ids, open_ids)` è la funzione pura testata: dato
l'insieme delle tracce presenti ora e quello delle tracce con stint aperto
(dallo stato), ritorna `(to_open, to_close, to_keep)`.

`EditorialsTracker(use_apify=…).run(dry_run=…)`:
1. fetch di **tutti** gli editoriali (skip + log su 404/errore/tracklist vuota);
2. `StateStore().load()`; se `None` → `_reconstruct_state(db)` (righe con
   `end_date IS NULL`; se la tabella non esiste ancora → stato vuoto, utile per
   `--dry-run` prima della creazione);
3. `diff_playlist` per ogni playlist; `ArtistResolver.load_db_map()`; raccolta
   dei `track_id` **solo tra i `to_open`** con un artista non noto → un
   `enrich_via_apify(...)` unico;
4. per editoriale: `UPDATE ... SET end_date = last_seen` per i `to_close`,
   `add_all` delle righe dei nuovi stint (una per traccia×artista; traccia senza
   artisti parseabili → una riga con `artist_name`/`artist_id` `NULL`), commit,
   poi aggiornamento in memoria del documento di stato e `StateStore().save(doc)`;
5. `--dry-run` logga il piano (nuovi stint, chiusure, mantenuti) e non scrive
   (né DB né file di stato); `--no-apify` salta il fallback.

### `cli.py` / `main.py` / env
`--dry-run`, `--no-apify`, `--log-level`. `main.py`: `load_dotenv()` →
`logging.basicConfig` → `EditorialsTracker(use_apify=not args.no_apify).run(...)`.
Env: `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT` (default 5432),
`SPOTIFY_API_KEY` (token Apify, stesso nome di ASP), `S3_BUCKET_NAME` +
`AWS_REGION` per il file di stato (non settati → file locale).

### Deploy
`terraform/` è la copia adattata di song_resolver_tracker: ECR repo
`editorials-playlist-app`, cluster/task ECS, ruoli IAM, **un** EventBridge
schedule giornaliero che lancia `uv run main.py`, ruolo GitHub OIDC per il push
immagini. `secrets_manager_keys` inietta `DB_*` **e** `SPOTIFY_API_KEY` da
Secrets Manager. `state_s3_bucket` → il task role ottiene
`s3:GetObject`/`s3:PutObject` su `editorial_playlist_state/*` e `S3_BUCKET_NAME` +
`AWS_REGION` finiscono nell'`environment` del container. Lo schedule nasce
`DISABLED` (review): passare a `ENABLED` e ri-applicare per far partire i run.

---

## Step 4 — Cosa si può fare con questi dati

`editorial_playlists_storico` è la **storia degli stint**. Le viste in
`sql/views.sql` (tutte in lettura, senza toccare la pipeline):

### `vw_editorial_current` — chi è dentro adesso
Le righe con `end_date IS NULL`: la tracklist corrente (traccia + artista) di
ogni editoriale ricostruita dallo storico. Base delle due viste sotto.

### a) In quanti editoriali è una traccia — `vw_track_editorial_count`
Per `track_id` (sulle righe "current"): numero di editoriali distinti e la lista
dei nomi. Confrontando due estrazioni nel tempo si vede se il conteggio sale (la
traccia si diffonde tra le curatele), resta piatto o cala (Spotify la sta
ritirando — spesso il primo segnale che l'onda è finita).

### b) In quanti editoriali è un artista — `vw_artist_editorial_count`
Come sopra ma per `artist_id` (una qualsiasi delle sue tracce): editoriali
distinti, tracce distinte, lista nomi. Utile per report artista-centrici.

### c) Durata degli stint — `vw_track_editorial_tenure`
Una riga per stint `(track_id, playlist_id, start_date, end_date)`:
`days_present = COALESCE(end_date, CURRENT_DATE) - start_date + 1` e `still_in`
(`end_date IS NULL`). Più righe per la stessa coppia = la traccia è entrata,
uscita e rientrata; la distanza tra `end_date` di uno stint e `start_date` del
successivo è il tempo passato fuori.

---

## Verifica end-to-end

1. `uv sync`; `.env` con `DB_*` e `SPOTIFY_API_KEY` (lascia `S3_BUCKET_NAME`
   vuoto per usare il file di stato locale).
2. `uv run python -m pytest` → verde (embed + artisti + state + `diff_playlist`).
3. `uv run main.py --dry-run --no-apify` → per ogni playlist logga
   `"<nome>: N tracks"` e il piano (open / close / keep); non scrive né DB né
   file di stato.
4. `uv run main.py` (primo giro) → tutto apre nuovi stint (`end_date` NULL);
   `select count(*), count(end_date) from
   social_golden_data.editorial_playlists_storico` (il secondo deve essere 0);
   `editorial_playlists` popolata con 15 righe; nasce `editorial_state.json`.
5. `uv run main.py` (secondo giro, stesso giorno) → no-op: 0 open, 0 close, solo
   `last_seen` aggiornato nel file di stato.
6. Simulare il giorno dopo (o attendere il run successivo): una traccia tolta a
   mano dal file di stato ricompare come nuovo stint; se sparisce dall'editoriale
   la sua riga prende `end_date`.
7. Applicare `sql/views.sql`; `select * from
   social_golden_data.vw_editorial_current where playlist_id = '…'`.
8. Deploy: `terraform apply` (passare `github_oidc_provider_arn`,
   `secrets_manager_arn`, `state_s3_bucket`), poi trigger manuale della task ECS
   e check dei CloudWatch logs.
