#!/usr/bin/env bash
# Copia al teléfono (adb) las canciones y playlists que falten o hayan cambiado.
# Uso: scripts/enviar-telefono.sh [--simular] [--destino "/sdcard/Download/Quick Share"] [carpeta]
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$PROJECT_DIR" || exit 1
exec "$PROJECT_DIR/.venv/bin/python" -u -m core.telefono "$@"
