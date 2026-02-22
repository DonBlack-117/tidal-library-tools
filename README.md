# tidal-library-tools

A set of Python scripts to manage your Tidal music library using the unofficial [`tidalapi`](https://github.com/tamland/python-tidal) API.

## Included tools

| Script | Description |
|--------|-------------|
| `sincronizar_tidal.py` | Searches for songs from your local folder in Tidal and adds them to *My Tracks* |
| `mejorar_calidad_tidal.py` | Replaces songs in *My Tracks* with higher audio quality versions |
| `limpiar_duplicados_tidal.py` | Detects and removes duplicate songs from *My Tracks* |

## Requirements

- Python 3.8 or higher
- Tidal account (HiFi or HiFi Plus recommended)

## Installation

```bash
pip install tidalapi
```

## Usage

Each script runs independently. The first time you run it, a browser window will open for you to log in to Tidal.

```bash
# Sync local music to Tidal
python sincronizar_tidal.py

# Upgrade audio quality of your library
python mejorar_calidad_tidal.py

# Remove duplicates
python limpiar_duplicados_tidal.py
```

## Notes

- Scripts respect a rate limit (`RATE_LIMIT_DELAY`) to avoid overloading the Tidal API.
- The session file (`tidal-session.json`) stores your authentication locally and is excluded from the repository for security.
- Result `.txt` files are also excluded from the repository.
