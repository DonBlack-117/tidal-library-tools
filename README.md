# tidal-library-tools

A set of Python tools to manage and download your Tidal music library using the unofficial [`tidalapi`](https://github.com/tamland/python-tidal) API and [`tiddl`](https://github.com/oskvr37/tiddl).

## Included tools

| Script | Description |
|--------|-------------|
| `core/sincronizar.py` | Searches for songs from your local folder in Tidal and adds them to *My Tracks* |
| `core/mejorar_calidad.py` | Replaces songs in *My Tracks* with higher audio quality versions |
| `core/limpiar_duplicados.py` | Detects and removes duplicate songs from *My Tracks* |
| `core/descargar.py` | Downloads tracks, albums, playlists or artists from Tidal via tiddl |

## Requirements

- Python 3.13 or higher
- Tidal account (HiFi or HiFi Plus recommended)
- [FFmpeg](https://ffmpeg.org/) installed and available in PATH (required for Stage 3)
- [tiddl](https://github.com/oskvr37/tiddl) authenticated (required for Stage 3)

## Installation

```bash
pip install -r requirements.txt
```

### FFmpeg (for downloading)

```powershell
winget install ffmpeg
```

### tiddl authentication (one-time setup)

```bash
tiddl auth login
```

A browser window will open. Complete the verification on the Tidal page.

## Usage

### Web interface (recommended)

```bash
python app.py
```

Then open **http://localhost:5000** in your browser. The interface guides you through a three-stage workflow:

1. **Stage 1 — Import:** select your local music folder and sync it to Tidal My Tracks
2. **Stage 2 — Optimize:** improve audio quality and remove duplicates directly in Tidal
3. **Stage 3 — Download:** download tracks, albums, playlists or artists from Tidal to your local machine in up to Hi-Res 24-bit quality

### Command line

Each script can also be run independently. The first time you run it, a browser window will open for you to log in to Tidal.

```bash
# Sync local music to Tidal
python core/sincronizar.py

# Upgrade audio quality of your library
python core/mejorar_calidad.py

# Remove duplicates
python core/limpiar_duplicados.py
```

## Project structure

```
tidal/
├── app.py                  # Flask web server
├── requirements.txt
├── core/                   # Core scripts
│   ├── sincronizar.py
│   ├── mejorar_calidad.py
│   ├── limpiar_duplicados.py
│   └── descargar.py        # tiddl wrapper (Stage 3)
├── static/js/              # Frontend
├── templates/              # HTML templates
└── logs/                   # Output logs (git-ignored)
```

## Notes

- Scripts respect a rate limit (`RATE_LIMIT_DELAY`) to avoid overloading the Tidal API.
- The session file (`tidal-session.json`) stores your tidalapi authentication locally and is excluded from the repository.
- tiddl credentials are stored in `~/.tiddl/` and excluded from the repository.
- Result `.txt` log files are saved to `logs/` and excluded from the repository.
