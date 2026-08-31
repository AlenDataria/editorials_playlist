# Documentazione editorials_playlist

Pipeline che traccia **la presenza e la posizione delle nostre canzoni Spotify
nelle playlist editoriali di Spotify Italia** nel tempo, per fornire a
clienti/A&R metriche di hype: in quanti editoriali è una canzone, da quanto, con
che posizione e con che trend.

Stesso impianto infrastrutturale di `song_resolver_tracker`: Docker + ECS Fargate
+ EventBridge (run giornaliero) + deploy via GitHub OIDC + Terraform.

---

## Step 1 — Cosa fa la pipeline

Una volta al giorno (ECS Fargate schedulato da EventBridge, 00:00 UTC):

1. Prende l'elenco degli editoriali da tracciare dalla costante `EDITORIALS` in
   [`src/consts.py`](src/consts.py).
2. Per ogni editoriale scarica la tracklist corrente dall'**endpoint embed
   pubblico** `https://open.spotify.com/embed/playlist/{ID}` (parse del blob
   `__NEXT_DATA__` nell'HTML) e ne ricava, in ordine,
   `(spotify_track_id, titolo, artisti, posizione)`. La posizione è l'indice
   1-based nella playlist (1° risultato = 1ª posizione).
3. Legge da `social_golden_data.spotify_tracks` (join `spotify_track_artists`)
   **solo le tracce con `active IS NOT false`**, con `spotify_id`, `track_name`,
   `album_name`, lista `artist_name`.
4. **Match** fra le tracce della playlist e le nostre tracce attive:
   - **primario**: uguaglianza sullo `spotify_id` — l'embed espone
     `spotify:track:<id>` nel campo `uri` di ogni traccia, quindi confronto
     diretto, zero falsi positivi;
   - **fallback**: match fuzzy titolo+artista (stessa logica del resolver) per i
     casi in cui il nostro DB ha la canzone sotto uno `spotify_id` diverso da
     quello messo da Spotify nell'editoriale (single vs album, ri-release, id
     regionale).
5. Per ogni traccia nostra trovata in un editoriale scrive **una riga snapshot**
   in `social_golden_data.editorial_playlist_entries` (colonne nello Step 3).
6. Commit per-editoriale (crash-safety); un editoriale che fallisce viene loggato
   e saltato senza abortire il run. `snapshot_date = date.today()`; rilanciare lo
   stesso giorno è idempotente (PK su `(playlist_id, spotify_id, snapshot_date)`).

### Perché l'endpoint embed e non l'API ufficiale
L'API ufficiale di Spotify restituisce **404** sugli editoriali (`37i9…`) per le
app in *development mode*, e il token anonimo del web player è stato bloccato da
Spotify (risponde citando i Developer Terms). L'endpoint embed è pubblico e senza
auth. Limiti noti, da tenere presente: (1) ritorna **max ~100 tracce** per
playlist — una più lunga viene troncata in silenzio (nessuna delle 16 tracciate
dovrebbe arrivarci; il codice logga un warning se la lista raggiunge il cap);
(2) **non espone il nome dell'album** per traccia — l'`album_name` sulle righe
snapshot viene quindi dai nostri dati; (3) la struttura JSON non è documentata e
può cambiare — il parsing è isolato in [`src/embed.py`](src/embed.py) e coperto
da test con una fixture.

---

## Step 2 — Editoriali tracciati

Elenco fisso, nella costante `EDITORIALS` ([`src/consts.py`](src/consts.py)) come
lista di dataclass `Editorial(playlist_id, name, segment, update_cadence,
viral_road)`. `segment` = per chi il piazzamento pesa di più. Il campo
`viral_road` è **solo documentazione**: in questa versione nessuna parte del
codice lo legge (vedi Step 4). EQUAL Italia esclusa su richiesta.

| Playlist | playlist_id | segment | viral_road (idea) | update |
|---|---|---|---|---|
| Viral 50 - Italia | `37i9dQZEVXbKbvcwe5owJ1` | both | breaking / anticipa | giornaliero |
| Top 50 - Italia | `37i9dQZEVXbIQnj7RRhdSX` | major | mainstream / conferma | giornaliero |
| Alta Rotazione | `37i9dQZF1DX01NP73ErE8b` | major | mainstream / momentum editoriale | +volte/settimana |
| Hot Hits Italia | `37i9dQZF1DX6wfQutivYYr` | major | mainstream / arrivo mainstream | ~2×/settimana |
| Hit Italiane | `37i9dQZF1DXcuVttLeQxkh` | major | mainstream / consolidata | settimanale |
| Big Italiani | `37i9dQZF1DX7zFcFgqJ2qf` | major | status (nomi grossi, non-hype) | settimanale |
| New Music Friday Italia | `37i9dQZF1DWVKDF4ycOESi` | both | on radar / uscita | settimanale (ven) |
| Novita Rap Italiano | `37i9dQZF1DX1OQlaot30zi` | both | on radar / uscita rap | settimanale (ven) |
| Novita Indie Italiano | `37i9dQZF1DX6O5gXioqvYB` | both | on radar / uscita indie | settimanale (ven) |
| nuovo pop Italia | `37i9dQZF1DX2c7QgpQBJFr` | emergent | on radar → gaining | settimanale |
| GENERAZIONE Z | `37i9dQZF1DWYCIYGXn56uz` | emergent | gaining / emergente con reach | settimanale |
| sanguegiovane | `37i9dQZF1DWW9tK1GiTdMf` | emergent | gaining / scena giovane | settimanale |
| anima R&B | `37i9dQZF1DWZuIX5Q3yUjF` | emergent | gaining / scena R&B | settimanale |
| Hit Rap Italiane | `37i9dQZF1DWSxF6XNtQ9Rg` | both | mainstream / urban | settimanale |
| Fresh Finds Italia | `37i9dQZF1DX0KBgD4Jf5tY` | emergent | on radar / il più precoce | settimanale |
| RADAR Italia | `37i9dQZF1DWVjDgOMO8jZl` | emergent | on radar / scommessa Spotify (~20 tracce) | rotazione lenta |

> **Viral 50 - Italia** — al 2026-08 Spotify **non la serve via embed** (l'endpoint
> risponde 404). È tenuta comunque in lista: la pipeline la salta con un WARNING
> (non un errore), così se Spotify riabilita l'embed i dati iniziano ad arrivare
> senza modifiche al codice. Resta il segnale "breaking" per la futura viral road.

---

## Step 3 — Implementazione tecnica

### Struttura del repo (mirror di song_resolver_tracker)

```
main.py                       # load_dotenv → parse_args → EditorialsTracker().run()
pyproject.toml                # deps: sqlmodel, psycopg2-binary, requests, python-dotenv (py ≥3.13, uv)
Dockerfile                    # python:3.13-slim + uv sync --frozen; CMD = uv run main.py
scripts/build_push_ecr.sh     # login + buildx (linux/amd64) + push su ECR
.github/workflows/deploy-ecr.yml   # push su main → build + push latest + SHA su ECR (GitHub OIDC)
terraform/                    # ECR, ECS cluster/task, ruoli IAM, 1 EventBridge schedule cron(0 0 * * ? *)
src/
  cli.py        # argparse: --dry-run, --log-level
  consts.py     # DB_SCHEMA, EMBED_URL, HTTP_HEADERS, REQUEST_*, RETRY_*, EDITORIALS
  db.py         # create_db_engine + retry_on_error + db_config_from_env (copia da song_resolver_tracker)
  models.py     # SQLModel: EditorialPlaylistEntry (owned), SpotifyTrack / SpotifyTrackArtists (read-only) + SourceTrack
  embed.py      # fetch_playlist_tracklist / parse_tracklist → list[PlaylistTrack]
  matching.py   # normalize, clean_title, is_title_match, is_artist_match, is_track_match (port da instagram/utils.py)
  processor.py  # EditorialsTracker: orchestrazione + scrittura snapshot
sql/
  views.sql     # viste dello Step 4 (conteggio / tenure / posizione)
tests/
  test_embed.py       # parsing __NEXT_DATA__ da fixture HTML
  test_matching.py     # casi feat. / variante / case
  fixtures/embed_playlist.html
```

### L'unica tabella — `social_golden_data.editorial_playlist_entries`

Di proprietà della pipeline, creata a runtime con
`EditorialPlaylistEntry.__table__.create(bind=engine, checkfirst=True)` (nessun
tool di migrazione nel progetto — stesso pattern di `tiktok_unresolved_tracks`).
Nessuna tabella-registro separata: l'elenco degli editoriali vive in `consts.py`.

| colonna | tipo | note |
|---|---|---|
| `playlist_id` | text | PK — id Spotify dell'editoriale |
| `spotify_id` | text | PK — `= spotify_tracks.spotify_id` |
| `snapshot_date` | date | PK — `date.today()` del run |
| `playlist_name` | text | nome editoriale (da `EDITORIALS`) |
| `track_name` | text | dai nostri dati |
| `artist_name` | text | artisti nostri, join con `", "` |
| `album_name` | text | dai nostri dati (l'embed non lo espone) |
| `position` | int | 1-based nella playlist |
| `created_at` | timestamptz | tecnico, default `now()` |

Grana: **una riga per (playlist, nostra traccia, giorno)**. Tabella append-only,
la storia si rigioca dalle righe.

### `embed.py` — scraping

`fetch_playlist_tracklist(playlist_id, session)` fa GET sull'embed (con
`@retry_on_error`, backoff esponenziale su `RequestException`/`EmbedParseError`),
poi `parse_tracklist(html)`:
- estrae il contenuto di `<script id="__NEXT_DATA__">` con una regex;
- naviga `props.pageProps.state.data.entity.trackList`;
- per ogni elemento con `entityType == "track"` e `uri` che inizia con
  `spotify:track:` crea un `PlaylistTrack(position, spotify_id, title, artists)`
  dove `position` è l'indice 1-based **sulla lista grezza** (gli elementi non-track
  non spostano la numerazione), `spotify_id` viene da `uri.split(":")[-1]`,
  `title` da `title`, `artists` da `subtitle` (stringa con i featuring
  concatenati, es. `"Angelina Mango, Marco Mengoni"`);
- se `len(trackList) >= 100` logga un warning "possibile troncamento".

Struttura JSON non ufficiale → tutto il parsing è qui e testato in
`tests/test_embed.py` con `tests/fixtures/embed_playlist.html`.

### `matching.py` — riuso della logica del resolver

Port da `song_resolver_tracker/src/platforms/instagram/utils.py`:
- `normalize(s)` → `(s or "").strip().casefold()`;
- `clean_title(s)` → rimozione **whitelist** di qualificatori di variante
  (Live/Acoustic/Sped Up/Remaster/…), sia come suffisso `" - ..."` sia come
  parentesi; `"(feat./ft/with/con ...)"` sempre rimosso; **mai** `"remix"` (è una
  registrazione distinta);
- `is_title_match` → containment bidirezionale su `clean_title` normalizzati;
- `is_artist_match` → **uno qualunque** dei nostri artisti compare come substring
  nella stringa artisti della playlist (tollera ordinamento diverso dei feat.);
- `is_track_match` → titolo AND artista.

È solo il **fallback**: il match primario nel processor è `spotify_id` esatto.

### `processor.py` — orchestrazione

`EditorialsTracker.__init__`: engine condiviso, `requests.Session` con
`HTTP_HEADERS` (User-Agent browser, l'embed dà 403 a un UA di libreria), create
table `checkfirst=True`.

`run(dry_run=False)`:
1. `_active_spotify_tracks(db)` — `select(spotify_id, track_name, album_name,
   array_agg(artist_name ORDER BY artist_id)).join(spotify_track_artists,
   isouter=True).where(active IS NOT false).group_by(spotify_id)` → `list[SourceTrack]`;
   `by_id = {t.spotify_id: t}`.
2. Per ogni `Editorial`: `fetch_playlist_tracklist` (skip + log su eccezione),
   poi `_match_rows`, poi log `"<nome>: N/M playlist tracks are ours"`.
3. `_match_rows`: scorre la playlist in ordine; per ogni `PlaylistTrack` prova
   `by_id.get(pt.spotify_id)` (match `spotify_id`), altrimenti scan lineare con
   `is_track_match` (match `fuzzy`, primo che matcha vince); tiene la **posizione
   minima** se una nostra traccia compare più volte nella stessa playlist;
   costruisce le righe `EditorialPlaylistEntry` con `track_name/artist_name/
   album_name` **dai nostri dati** e `position` dalla playlist. `--dry-run` logga
   le righe e non scrive.
4. `db.add(r)` per riga, `db.commit()` per editoriale (rollback + log su errore,
   si prosegue), `time.sleep(REQUEST_DELAY)` tra un editoriale e l'altro.

### `cli.py` / `main.py` / env
`--dry-run` (scarica e logga i match, non scrive), `--log-level`. `main.py`:
`load_dotenv()` → `logging.basicConfig` → `EditorialsTracker().run(...)`.
Env: `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_PORT` (default 5432) —
stessi nomi di ASP e song_resolver_tracker.

### Deploy
`terraform/` è la copia adattata di song_resolver_tracker: ECR repo
`editorials-playlist-app`, cluster/task ECS, ruoli IAM, **un** EventBridge
schedule giornaliero che lancia `uv run main.py`, ruolo GitHub OIDC per il push
immagini. Backend state su bucket S3 `editorials-playlist-tfstate`.
`create_github_oidc_provider` di default `false` (l'account ne ha già uno creato
da song_resolver_tracker: passare `github_oidc_provider_arn`). Secret: solo i
`DB_*` da Secrets Manager, nessuno nuovo. `.github/workflows/deploy-ecr.yml`
builda e pusha `latest` + SHA a ogni push su `main`.

### Perché non serve threading
16 playlist × 1 richiesta HTTP = carico banale; il resolver stesso è sequenziale
con commit per-item. Nessun `pipeline.py` produttore/consumatore.

---

## Step 4 — Cosa si può fare con questi dati

L'unica tabella `editorial_playlist_entries` è una **fotografia giornaliera**:
"in questo giorno, questa nostra canzone era in questo editoriale, a questa
posizione". Accumulando le fotografie si ottiene una serie storica per ogni
coppia canzone↔editoriale, e da lì si ricavano — **tutto in lettura, con viste
SQL in [`sql/views.sql`](sql/views.sql), senza toccare la pipeline** — quattro
tipi di informazione. Le prime tre sono implementate subito; la quarta (viral
road) è per ora solo un'idea.

### a) In quanti editoriali è una canzone, e quali — `vw_track_editorial_count`

**A cosa serve.** È l'indicatore più immediato di "quanto Spotify sta spingendo"
una canzone. Una traccia in 1 editoriale di nicchia e una in 6 editoriali diversi
(dalle novità fino a Hot Hits) raccontano due momenti di carriera opposti. Per un
cliente è il numero da mettere in cima a un report; per l'A&R è il modo di
confrontare a colpo d'occhio due uscite dello stesso periodo.

**Come si legge.** Per ogni giorno, quante righe ha quella `spotify_id` e su
quali `playlist_name`. Guardando la serie nel tempo si vede se il conteggio sale
(la canzone si sta diffondendo tra le curatele), resta piatto (spinta stabile) o
cala (Spotify la sta ritirando dalle rotazioni — spesso il primo segnale che
l'onda è finita).

### b) Da quanto tempo è in un editoriale — `vw_track_editorial_tenure`

**A cosa serve.** La permanenza è un proxy di quanto quel piazzamento sta
"lavorando". Una settimana in New Music Friday è fisiologica (si svuota ogni
venerdì); tre mesi in Hit Italiane vogliono dire che la canzone è diventata
catalogo corrente. Serve per dire a un cliente "il tuo pezzo è in Alta Rotazione
da 24 giorni" invece che solo "è in Alta Rotazione", e per capire quando una
spinta si sta esaurendo.

**Come si legge.** Per ogni coppia `(canzone, editoriale)`: primo giorno visto,
ultimo giorno visto, giorni totali presenti, e `still_in` (l'ultimo giorno visto
è lo snapshot più recente in tabella → è ancora dentro). La differenza tra
"giorni totali" e la finestra `first_seen…last_seen` dice se è stata dentro di
fila o se è rientrata dopo essere uscita — i rientri sono rari e di solito legati
a un evento nuovo (un feat., un trend TikTok, un live). Se in futuro serve
distinguere una permanenza continua da più rientri separati, si isolano i blocchi
consecutivi con il classico `snapshot_date - row_number()` gap-and-islands.

### c) Posizione, e se sta salendo o scendendo — `vw_track_position_trend`

**A cosa serve.** La posizione è il segnale più fine che l'embed dà. Spotify
riordina le playlist mettendo più in alto ciò su cui vuole puntare in quel
momento: una canzone che passa dalla #40 alla #8 di Hot Hits in pochi giorni sta
ricevendo una spinta crescente, anche se il numero di editoriali non è cambiato.
È il dato che anticipa i movimenti di stream, non che li insegue.

**Come si legge.** Per ogni coppia `(canzone, editoriale)`, la posizione di oggi
confrontata con quella della rilevazione precedente (`lag`). `delta > 0` = è
salita (verso la #1), `delta < 0` = è scesa. Un `delta` negativo costante per più
giorni è tipicamente il preludio all'uscita dall'editoriale. Due limiti da
comunicare: (1) l'embed si ferma a ~100 tracce, quindi una canzone oltre la #100
"scompare" anche se è ancora in playlist; (2) alcuni editoriali (Viral 50,
Top 50) sono classifiche di consumo — lì la posizione riflette gli stream reali,
non una scelta editoriale, e va letta diversamente dalle playlist curate.

### d) Viral road — *idea, da sviluppare più avanti*

**Non è implementata**: nessuna colonna, nessuna vista, nessuna logica. Qui è
scritta come direzione.

**L'idea.** I 16 editoriali non sono tutti sullo stesso piano: alcuni sono il
posto dove una canzone *arriva appena esce*, altri dove finisce *solo se sta
esplodendo*. Se li raggruppiamo per "quanto in là nella scalata" rappresentano,
la presenza di una canzone in quei gruppi diventa un modo per dire a che punto è
del suo percorso virale — la "viral road":

- **on radar** — la canzone è solo negli editoriali di uscita/scoperta (New Music
  Friday Italia, Novita Rap/Indie, Fresh Finds Italia, RADAR Italia, nuovo pop).
  Spotify l'ha notata e le ha dato la vetrina di default per una nuova uscita, ma
  non c'è ancora traino.
- **gaining** — entra negli editoriali di scena/target (GENERAZIONE Z,
  sanguegiovane, anima R&B, Hit Rap Italiane). Sta funzionando con un pubblico
  specifico; gli editor la stanno passando da "novità" a "cosa che gira".
- **breaking** — compare in **Viral 50 - Italia**. È lo spartiacque: la Viral 50
  misura velocità di salvataggi/condivisioni, non stream assoluti, quindi ci
  arrivano i pezzi che accelerano *prima* di essere grossi. Una canzone che passa
  da "on radar" a "breaking" è il momento in cui il trend diventa reale.
- **mainstream** — entra in Top 50 - Italia, Alta Rotazione, Hot Hits Italia, Hit
  Italiane. È diventata consumo di massa; qui si misura la durata, non più la
  scoperta.

**Come diventerebbe un dato.** Lo *stage corrente* di una canzone in un dato
giorno sarebbe il gruppo più avanzato tra gli editoriali in cui è presente quel
giorno (se è in New Music Friday **e** in Viral 50, lo stage è "breaking"). Sopra
si costruisce quello che davvero interessa: la **timeline degli stage** di una
canzone (quando è passata da on radar a gaining a breaking, e quanto ci ha messo)
e l'**alert sulla transizione chiave** — una traccia che era negli editoriali di
novità e oggi entra per la prima volta in Viral 50. Big Italiani resterebbe fuori
dal calcolo: è una playlist di status (nomi già affermati), non un gradino della
scalata.

**Cosa manca per farla.** Solo una decisione di prodotto: la mappatura
editoriale→stage (già abbozzata nel campo `viral_road` di `EDITORIALS`) e la
definizione esatta di "transizione". Quando saranno stabili si aggiunge una vista
`vw_track_viral_road` sopra la **stessa** `editorial_playlist_entries` — la
raccolta dati di oggi è già sufficiente, non serve raccogliere nulla di nuovo.

---

## Verifica end-to-end

1. `uv sync`; `.env` con le credenziali DB (come le altre repo).
2. `uv run python -m pytest` → parsing embed + matching verdi.
3. `uv run main.py --dry-run` → per ogni playlist logga `"<nome>: N/M playlist
   tracks are ours"` e le righe che scriverebbe; verificare a mano 1–2 match
   (es. una nostra traccia nota presente in "Alta Rotazione").
4. `uv run main.py` → `select count(*), max(snapshot_date) from
   social_golden_data.editorial_playlist_entries`; controllare che `position`
   parta da 1 e che `playlist_name` sia valorizzato.
5. Applicare `sql/views.sql`; interrogare `vw_track_editorial_count` e
   `vw_track_position_trend` per una traccia campione.
6. Rilanciare lo stesso giorno → nessun duplicato (PK
   `(playlist_id, spotify_id, snapshot_date)`), run idempotente.
7. Deploy: `terraform apply` (passare `github_oidc_provider_arn`,
   `secrets_manager_arn`), poi trigger manuale della task ECS e controllo dei
   CloudWatch logs.
