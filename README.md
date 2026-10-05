# tidal-library-tools

A set of Python tools to manage and download your Tidal music library using the unofficial [`tidalapi`](https://github.com/tamland/python-tidal) API and [`tiddl`](https://github.com/oskvr37/tiddl).

## Included tools

| Script | Description |
|--------|-------------|
| `core/sincronizar.py` | Searches for songs from your local folder in Tidal and adds them to *My Tracks* |
| `core/mejorar_calidad.py` | Replaces songs in *My Tracks* with higher audio quality versions |
| `core/limpiar_duplicados.py` | Detects and removes duplicate songs from *My Tracks* |
| `core/recursos.py` | Downloads whatever a Tidal link points to (track, album, playlist, artist, mix) or all of *My Tracks*, skipping what you already have |
| `core/descargar.py` | tiddl wrapper used by `core/recursos.py` (two passes for Dolby Atmos, retries, stall watchdog) |
| `scripts/descargar-my-tracks.sh` | One-click download of all of *My Tracks* (no web UI needed) |

## Requirements

- Python 3.13 or higher
- Tidal account (HiFi or HiFi Plus recommended)
- [FFmpeg](https://ffmpeg.org/) installed and available in PATH (required for Stage 3)
- [tiddl](https://github.com/oskvr37/tiddl) authenticated (required for Stage 3)

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Tidal session (one-time setup)

```bash
.venv/bin/python -m core.hires login
```

It opens the browser; after logging in, Tidal shows an "Oops" page: paste its URL in the terminal. This PKCE session is saved to `tidal-pkce.session.json` (git-ignored) and is shared by the link preview, My Tracks, playlists, Hi-Res and the three My Tracks tools, so none of them opens the browser again.

### FFmpeg (for downloading)

```bash
sudo dnf install ffmpeg-free   # Fedora
# Windows: winget install ffmpeg
```

### tiddl authentication (one-time setup)

tiddl has its own session and is used only to download:

```bash
.venv/bin/tiddl auth login
```

A browser window will open. Complete the verification on the Tidal page.

## Usage

### Web interface (recommended)

```bash
.venv/bin/python app.py
```

Then open **http://localhost:5000** in your browser.

**Download anything by pasting a link.** Paste into the box (or press Ctrl+V anywhere on the page) any of these:

- a link: `https://tidal.com/browse/track/…`, `listen.tidal.com/album/…`, `tidal.com/playlist/…`, `…/artist/…`, `…/mix/…`
- the whole text the Tidal app copies with *Share* ("Escucha … en TIDAL https://tidal.com/track/…/u")
- a shorthand like `album/123` or just an ID (numbers are tracks, a UUID is a playlist)

A preview shows what it is and how many songs you already have, are missing, or are unavailable on Tidal. Only the missing ones are downloaded. Artists (the whole discography) and mixes ask for confirmation first. Playlists and mixes also get a `.m3u8`.

**Pick songs from My Tracks or a playlist.** The My Tracks button shows how many favorites are new (`989 favoritos · 12 nuevas por descargar`) and opens a window with every song: a checkbox per song, a search box (ignores accents), "Marcar las que faltan", and at the top **Descargar todo** and **Descargar seleccionadas (N)**. Songs already on disk or unavailable on Tidal are shown but cannot be ticked. Choosing a playlist from your account opens the same window, and so does **Elegir canciones** in the preview of a pasted album, playlist, mix or artist. With a partial selection, a playlist's `.m3u8` lists only the songs on disk.

Only one operation runs at a time. The server only answers requests from its own page (`localhost`, JSON, same origin), so other websites open in the browser cannot trigger downloads or shut it down.

The rest of the page: playlists from your account (choosing one fills the preview), Hi-Res upgrade, copy to the phone, and the My Tracks tools (higher quality versions, remove duplicates, import a local folder).

## Stage 3 — Download (tiddl 3.4.3)

Downloads always use the **maximum quality** Tidal serves for each track (Hi-Res FLAC, Lossless FLAC, or AAC when that is all there is), with embedded cover art (1280×1280), embedded lyrics plus a `.lrc` file when Tidal has lyrics, and full metadata (title, artists, album, album artist, track/disc number, date, ISRC, copyright).

tiddl 3.4 has no `tiddl config` command: all of this comes from `~/.tiddl/config.toml` (or `$TIDDL_PATH/config.toml`), which is validated strictly. Required settings:

```toml
[metadata]
enable = true
lyrics = true
cover = true

[cover]
size = 1280

[download]
track_quality = "max"
atmos_filter = "allow"
skip_existing = true
write_lrc_file = true
download_path = "~/Music/Tidal"

[templates]
default = "{album.artist}/{album.title}/{item.number:02d} - {item.title}"
```

**My Tracks** looks up the ISRC of every favorite (cached in `<dir>/.tidal_ids.json`, so only new favorites are queried), compares it with the files already in `<dir>/canciones`, and downloads only the missing ones with `tiddl download -q max url track/<id> ...` (default folder `~/Music/Tidal`). Favorites Tidal no longer has (404) are recorded and skipped.

### Hi-Res (24-bit)

Tidal only serves Hi-Res streams to **PKCE** sessions; with tiddl's session a track tagged `HIRES_LOSSLESS` arrives as 16-bit/44.1 kHz. `core/hires.py` fixes that with tidalapi's documented PKCE login (the same one High Tide uses):

```bash
.venv/bin/python -m core.hires login   # once: log in in the browser, paste the "Oops" page URL
.venv/bin/python -m core.hires         # upgrade every pending 16-bit FLAC in ~/Music/Tidal/canciones
```

After every download the upgrade runs automatically. For each 16-bit FLAC that Tidal has in Hi-Res it downloads the DASH stream, extracts the FLAC with ffmpeg, copies tags, cover and lyrics from the current file, verifies it (bit depth, cover, ISRC, full decode) and only then replaces it. Results are cached in `~/Music/Tidal/.hires.json`. Encrypted streams are skipped, never decrypted. The session is stored in `tidal-pkce.session.json` (git-ignored). The one-click script asks for the login the first time.

### Playlists

```bash
.venv/bin/python -m core.recursos "https://tidal.com/playlist/<uuid>"
```

Like any link, only the tracks whose ISRC is not already in `canciones/` are downloaded (same tiddl + flatten + Hi-Res flow as My Tracks). Playlists and mixes then get two `.m3u8` files in Tidal's order:

- `~/Music/Tidal/playlists/<name>.m3u8`: paths `../canciones/<file>`.
- `~/Music/Tidal/playlists/plana/<name>.m3u8`: bare file names, to drop next to the songs in a flat folder (e.g. the phone's `Download/Quick Share`, where Poweramp imports it as a playlist).

File names never contain `" : * ? < > | \`, because Android shared storage rejects them (`"` becomes `'`).

### Copy to the phone

```bash
scripts/enviar-telefono.sh --simular   # show what would be copied
scripts/enviar-telefono.sh             # copy via adb to /sdcard/Download/Quick Share
```

`core/telefono.py` needs exactly one device with USB (or wireless) debugging. It copies every song from `canciones/` and every `.m3u8` from `playlists/plana/` that is missing on the phone or has a different size (e.g. upgraded to Hi-Res later), then checks that both sides match. It never deletes anything on the phone. Use `--destino` for another folder. After copying, Poweramp picks the files up on its next scan (Settings → Library → Rescan).

### Flat library layout

tiddl downloads into `<dir>/.descarga` using the template above; `core/biblioteca.py` then moves everything into a flat layout, with no subfolders and no track number in the name:

```
~/Music/Tidal/
├── canciones/   # all audio: "Work REMIX (feat. ...).flac"
└── lyrics/      # matching .lrc files, same name as the song
```

- When two songs share a title, the artist is appended (`Alone - Alan Walker`), then the album if needed.
- Dolby Atmos versions keep the ` [Dolby Atmos]` suffix.
- A download whose ISRC and format already exist in `canciones/` is discarded (this also applies to URL downloads).

**Dolby Atmos:** for tracks that have both mixes, Tidal returns only the Atmos stream to tiddl. A second pass (`core/tiddl_estereo.py`, which adds the standard `immersiveaudio=false` API parameter) downloads the stereo FLAC as well; the Atmos file is kept alongside as `NN - Title [Dolby Atmos].m4a`. Nothing is decrypted: an Atmos file that arrives encrypted or can't be decoded is deleted and listed (title and ID) in `logs/tidal_atmos_omitidas.txt`. Other tiddl errors are written to `logs/tidal_descarga_errores.txt`. tiddl writes ISRC only to FLAC, so it is added to `.m4a` files afterwards.

## One-click download of My Tracks

Without opening the web UI:

```bash
scripts/descargar-my-tracks.sh            # → ~/Music/Tidal
scripts/descargar-my-tracks.sh /other/dir
```

It uses the project `.venv`, checks the tiddl session, and writes a log to `logs/tidal_my_tracks_<date>.log`. On Linux, the launcher `~/.local/share/applications/tidal-my-tracks.desktop` (icon `img/icontidal.png`) runs it from the app menu in a terminal:

```ini
[Desktop Entry]
Type=Application
Name=Tidal My Tracks
Exec="/path/to/tidal/scripts/descargar-my-tracks.sh" --pausa
Icon=/path/to/tidal/img/icontidal.png
Terminal=true
Categories=AudioVideo;Audio;Music;
```

If the session has expired, run `.venv/bin/tiddl auth login` once.

### Command line

Each tool can also be run on its own (they use the saved Tidal session):

```bash
.venv/bin/python -m core.sincronizar          # sync local music to Tidal
.venv/bin/python -m core.mejorar_calidad      # upgrade audio quality of My Tracks
.venv/bin/python -m core.limpiar_duplicados   # remove duplicates
.venv/bin/python -m core.recursos mytracks [folder]              # download My Tracks
.venv/bin/python -m core.recursos "<Tidal link or share text>" [folder]
```

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/playwright install chromium    # first time only, for the page tests
.venv/bin/python -m pytest
```

They use a fake Tidal session and a fake tiddl, so they never touch your account or download anything. `tests/e2e/` runs the real Flask server and drives the page with Playwright. The library tests need FFmpeg to create small FLAC files.

## Frontend

Tailwind is compiled to `static/css/app.css` (committed), and the Geist fonts are in `static/vendor/fonts`, so the page works without internet. After changing classes in `templates/` or `static/js/`, rebuild the CSS (needs Node):

```bash
scripts/construir-css.sh
```

## Project structure

```
tidal/
├── app.py                  # Flask web server
├── requirements.txt, requirements-dev.txt, pytest.ini
├── core/
│   ├── enlaces.py          # parses pasted links, share text and IDs
│   ├── recursos.py         # preview and download of any link or My Tracks
│   ├── sesion.py           # shared Tidal (PKCE) session
│   ├── descargar.py        # tiddl wrapper
│   ├── tiddl_estereo.py    # tiddl runner that requests the stereo mix
│   ├── biblioteca.py       # flat library, ISRC index, stats
│   ├── hires.py            # Hi-Res upgrade and `login`
│   ├── playlists.py        # account playlists and .m3u8 files
│   ├── telefono.py         # copy to the phone over adb
│   ├── sincronizar.py, mejorar_calidad.py, limpiar_duplicados.py
├── scripts/
│   ├── descargar-my-tracks.sh  # one-click My Tracks download
│   └── construir-css.sh        # rebuild static/css/app.css
├── static/js/              # ES modules (main, descargar, operacion, …)
├── static/css/, static/vendor/fonts/
├── templates/
├── tests/                  # pytest; tests/e2e with Playwright
└── logs/                   # Output logs (git-ignored)
```

## Notes

- Scripts respect a rate limit (`RATE_LIMIT_DELAY`) to avoid overloading the Tidal API.
- The session file (`tidal-pkce.session.json`) stores your tidalapi authentication locally and is excluded from the repository.
- tiddl credentials are stored in `~/.tiddl/` and excluded from the repository.
- Result `.txt` log files are saved to `logs/` and excluded from the repository.
