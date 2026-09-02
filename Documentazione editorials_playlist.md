# Documentazione editorials_playlist

Pipeline che tiene aggiornata la storia di **tutte le tracce** presenti nelle
playlist editoriali di Spotify Italia che seguiamo. Non una riga al giorno, ma
**una riga per _stint_** — un periodo continuo di permanenza di una traccia in un
editoriale — con `start_date` ed `end_date`, una riga per nome artista accreditato.
Da qui si ricava in quanti editoriali è una traccia, da quando e per quanto.

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
3. **Diff sugli stint.** Il **DB è lo stato**: gli stint aperti sono le righe con
   `end_date IS NULL`. Si legge `SELECT DISTINCT playlist_id, track_id FROM
   editorial_playlists_storico WHERE end_date IS NULL` e per ogni editoriale
   scaricato si confrontano le tracce presenti ora con quelle aperte:
   - traccia presente, **nessuno** stint aperto → **nuovo stint**: una riga per
     nome artista con `start_date = oggi`, `end_date = NULL`;
   - traccia presente, stint **già aperto** → niente;
   - traccia con stint aperto, **non più presente** → `end_date = oggi`.
4. **Scrittura.** Per editoriale: un `UPDATE ... SET end_date = oggi` per le
   chiusure + `add_all` delle nuove righe, commit. Re-run nello stesso giorno =
   no-op (tutte le tracce già aperte → `to_keep`, niente da scrivere).

### Protezioni sulle response

- **Fetch fallito / tracklist vuota** → playlist saltata, stint aperti intatti.
- **Response parziale** — la tracklist scaricata ha `PARTIAL_RESPONSE_DROP` (20)
  o più tracce **in meno** rispetto agli stint attualmente aperti per quella
  playlist → considerata rotta: playlist saltata, DB non toccato, `WARNING`.
  Un ricambio legittimo (New Music Friday) ha una tracklist di dimensione
  normale e non fa scattare la guardia. Una playlist che si rimpicciolisce
  **davvero** continua a loggare `WARNING` a ogni run finché non si sistema a
  mano.
- **Circuit breaker** — se più di metà degli editoriali vengono saltati in un
  run, il run abortisce con `exit(1)` (la task ECS risulta fallita) senza
  scrivere niente.
- **Metrica** — ogni run stampa su stdout `{"metric":
  "editorials_playlists_skipped", "value": N}`; `terraform/alarms.tf` la
  trasforma in metrica CloudWatch con allarme su `> 0`.

> **Limite noto (rischio accettato).** Se una traccia sparisce dall'embed per un
> solo giro (glitch, troncamento a 100) e poi ricompare — senza far scattare la
> guardia "response parziale" — viene chiusa e riaperta come nuovo stint: nello
> storico due periodi con un buco di un giorno. Si ricuce lato SQL a valle se
> diventa ricorrente.

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
main.py                       # load_dotenv → parse_args → EditorialsTracker().run()
pyproject.toml                # deps: sqlmodel, psycopg2-binary, requests, python-dotenv
Dockerfile                    # python:3.13-slim + uv sync --frozen; CMD = uv run main.py
terraform/                    # ECR, ECS cluster/task, ruoli IAM, EventBridge schedule + alarm
src/
  cli.py        # argparse: --dry-run, --log-level
  consts.py     # DB_SCHEMA, EMBED_URL, HTTP_HEADERS, REQUEST_*, RETRY_*, PARTIAL_RESPONSE_DROP, EDITORIALS
  db.py         # create_db_engine + retry_on_error + db_config_from_env
  models.py     # SQLModel: EditorialPlaylist, EditorialPlaylistStorico (owned)
  embed.py      # fetch_playlist_tracklist / parse_tracklist → list[PlaylistTrack]
  artists.py    # split_artist_names (embed subtitle → lista nomi)
  processor.py  # EditorialsTracker: fetch → guardie → diff vs righe aperte del DB → apri / chiudi stint
sql/
  schema.sql    # DDL delle due tabelle
  views.sql     # viste read-time (chi è dentro ora, conteggi per traccia/nome-artista, tenure)
tests/
  test_embed.py           # parsing __NEXT_DATA__ da fixture HTML
  test_artists.py         # split_artist_names
  test_processor_plan.py  # diff_playlist + is_partial_response
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

**`editorial_playlists_storico`** — uno stint per riga (una riga per nome artista).

| colonna | tipo | note |
|---|---|---|
| `id` | bigint identity | PK surrogata |
| `playlist_id` | text | FK → `editorial_playlists.playlist_id` |
| `playlist_name` | text | denormalizzato, comodo per le viste |
| `track_name` | text | titolo lato playlist |
| `track_id` | text | id Spotify della traccia (dall'embed) |
| `artist_name` | text | un artista accreditato (split della stringa embed); `NULL` se non parseabile |
| `start_date` | date | primo run che ha visto la traccia in questo stint |
| `end_date` | date NULL | `NULL` finché la traccia è in playlist; alla chiusura = data del run che l'ha trovata sparita |

Grana: **una riga per (playlist, traccia, nome artista, stint)**. Lo storico
**è** lo stato: stint aperto = `end_date IS NULL` (= "traccia dentro adesso",
vista `vw_editorial_current`). Indice unico parziale `ux_eps_open` su
`(playlist_id, track_id, COALESCE(artist_name,'')) WHERE end_date IS NULL` → una
sola riga aperta per (playlist, traccia, nome artista). Rientro dopo un'uscita =
nuova riga. Re-run nello stesso giorno = no-op.

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

### `artists.py`

Solo `split_artist_names(subtitle)` → split su `","` con strip (il caso raro di
un nome che contiene una virgola, es. "Tyler, The Creator", viene spezzato —
accettato). Lo storico tiene una riga per ogni nome così ottenuto.

### `processor.py` — orchestrazione

Due funzioni pure testate:
- `diff_playlist(present_ids, open_ids)` → `(to_open, to_close, to_keep)`;
- `is_partial_response(present_count, open_count)` → `True` se
  `open_count - present_count >= PARTIAL_RESPONSE_DROP` (20).

`EditorialsTracker().run(dry_run=…)`:
1. fetch di **tutti** gli editoriali (skip + log su 404/errore/tracklist vuota),
   i nomi dei falliti in `fetch_failed`;
2. `_open_stints(db)` → `{playlist_id: {track_id}}` da `end_date IS NULL` (se la
   tabella non esiste ancora → dict vuoto + warning, per `--dry-run`);
3. `diff_playlist` + `is_partial_response` per ogni playlist; le parziali vanno
   in `partial` con un `WARNING`;
4. `skipped = len(fetch_failed) + len(partial)` → stampa
   `{"metric": "editorials_playlists_skipped", "value": skipped}` su stdout;
5. **circuit breaker**: se `skipped > len(EDITORIALS)//2` → `ERROR` + `exit(1)`
   (in `--dry-run` solo `ERROR` e `return`), niente scritture;
6. per editoriale **non** parziale: un `UPDATE ... SET end_date = oggi` per i
   `to_close` (`track_id IN (...) AND end_date IS NULL`), `add_all` delle righe
   dei nuovi stint (una per nome artista; traccia senza artisti parseabili → una
   riga con `artist_name` `NULL`), commit;
7. riga finale: `fetched N/15, opened X, closed Y, skipped Z [lista playlist]`;
8. `--dry-run` logga il piano e non scrive.

### `cli.py` / `main.py` / env
`--dry-run`, `--log-level`. `main.py`: `load_dotenv()` → `logging.basicConfig` →
`EditorialsTracker().run(dry_run=…)`. Env: solo `DB_HOST`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_PORT` (default 5432).

### Deploy
`terraform/` è la copia adattata di song_resolver_tracker: ECR repo
`editorials-playlist-app`, cluster/task ECS, ruoli IAM, **un** EventBridge
schedule giornaliero che lancia `uv run main.py`, ruolo GitHub OIDC per il push
immagini. `secrets_manager_keys` inietta solo `DB_*` da Secrets Manager.
`alarms.tf` → log-metric-filter sulla riga JSON `editorials_playlists_skipped` +
`aws_cloudwatch_metric_alarm` su `> 0` (azione SNS opzionale via
`alarm_sns_topic_arn`). Lo schedule nasce `DISABLED` (review): passare a
`ENABLED` e ri-applicare per far partire i run.

---

## Step 4 — Cosa si può fare con questi dati

`editorial_playlists_storico` è la **storia degli stint**. Le viste in
`sql/views.sql` (tutte in lettura, senza toccare la pipeline):

### `vw_editorial_current` — chi è dentro adesso
Le righe con `end_date IS NULL`: la tracklist corrente (traccia + nome artista)
di ogni editoriale ricostruita dallo storico. Base delle due viste sotto.

### a) In quanti editoriali è una traccia — `vw_track_editorial_count`
Per `track_id` (sulle righe "current"): numero di editoriali distinti e la lista
dei nomi. Confrontando due estrazioni nel tempo si vede se il conteggio sale (la
traccia si diffonde tra le curatele), resta piatto o cala (Spotify la sta
ritirando — spesso il primo segnale che l'onda è finita).

### b) In quanti editoriali è un artista — `vw_artist_editorial_count`
Come sopra ma per `artist_name` (una qualsiasi delle sue tracce): editoriali
distinti, tracce distinte, lista nomi. Attenzione alle omonimie e alle varianti
di scrittura dei feat. (niente `artist_id` in questa pipeline).

### c) Durata degli stint — `vw_track_editorial_tenure`
Una riga per stint `(track_id, playlist_id, start_date, end_date)`:
`days_present = COALESCE(end_date, CURRENT_DATE) - start_date + 1` e `still_in`
(`end_date IS NULL`). Più righe per la stessa coppia = la traccia è entrata,
uscita e rientrata; la distanza tra `end_date` di uno stint e `start_date` del
successivo è il tempo passato fuori.

---

## Verifica end-to-end

1. `uv sync`; `.env` con i soli `DB_*`.
2. `uv run python -m pytest` → verde (embed + `split_artist_names` +
   `diff_playlist` + `is_partial_response`).
3. `uv run main.py --dry-run` → per ogni playlist logga `"<nome>: N tracks"` e
   il piano (open / close / keep); stampa la riga `metric` e il summary; non
   scrive.
4. `uv run main.py` (primo giro) → tutto apre nuovi stint (`end_date` NULL);
   `select count(*), count(end_date) from
   social_golden_data.editorial_playlists_storico` (il secondo deve essere 0);
   `editorial_playlists` popolata con 15 righe.
5. `uv run main.py` (secondo giro, stesso giorno) → no-op: 0 open, 0 close,
   `skipped 0`.
6. Chiudere a mano una riga (`update ... set end_date = current_date where ...`)
   e verificare che al run successivo la traccia ricompare come **nuovo** stint;
   una traccia sparita dall'editoriale prende `end_date`.
7. Guardia: troncare a mano l'input (o simulare) così una playlist torna con
   ≥ 20 tracce in meno degli stint aperti → `WARNING` "PARTIAL", quella playlist
   non tocca il DB, `metric value` incrementato.
8. Applicare `sql/views.sql`; `select * from
   social_golden_data.vw_editorial_current where playlist_id = '…'`.
9. Deploy: `terraform apply` (passare `github_oidc_provider_arn`,
   `secrets_manager_arn`, opz. `alarm_sns_topic_arn`), poi trigger manuale della
   task ECS e check dei CloudWatch logs + allarme.
