#!/usr/bin/env bash
# Descarga todas las pistas de "My Tracks" (favoritos de Tidal) en calidad máxima.
# Uso: scripts/descargar-my-tracks.sh [--pausa] [carpeta]   (por defecto ~/Music/Tidal)
#      --pausa  espera Enter al final (lo usa el lanzador .desktop)
set -uo pipefail

PAUSA=0
if [[ "${1:-}" == "--pausa" ]]; then PAUSA=1; shift; fi
pausar() { [[ $PAUSA -eq 1 ]] && read -rp "Pulsa Enter para cerrar..." _; }

PROJECT_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PYTHON="$PROJECT_DIR/.venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/tidal_my_tracks_$(date +%Y%m%d-%H%M%S).log"

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR" || exit 1

if [[ ! -x "$PYTHON" ]]; then
    echo "❌ No se encontró $PYTHON. Crea el entorno: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" | tee "$LOG_FILE"
    pausar; exit 1
fi

if ! "$PROJECT_DIR/.venv/bin/tiddl" auth refresh >>"$LOG_FILE" 2>&1; then
    echo "❌ La sesión de tiddl no es válida. Ejecuta: $PROJECT_DIR/.venv/bin/tiddl auth login" | tee -a "$LOG_FILE"
    command -v notify-send >/dev/null && notify-send -i "$PROJECT_DIR/img/icontidal.png" "Tidal My Tracks" "Sesión caducada: ejecuta tiddl auth login"
    pausar; exit 1
fi

# Hi-Res necesita una sesión PKCE de tidalapi (una sola vez, en el navegador)
if [[ ! -f "$PROJECT_DIR/tidal-pkce.session.json" && -t 0 ]]; then
    echo "🔑 Falta la sesión Hi-Res de Tidal (solo se pide una vez)."
    "$PYTHON" -m core.hires login || echo "⚠ Sin sesión Hi-Res: se descargará en 16-bit"
    echo
fi

"$PYTHON" -u -m core.descargar "${1:-}" 2>&1 | tee -a "$LOG_FILE"
CODE=${PIPESTATUS[0]}

echo "Log: $LOG_FILE"
if command -v notify-send >/dev/null; then
    if [[ $CODE -eq 0 ]]; then
        notify-send -i "$PROJECT_DIR/img/icontidal.png" "Tidal My Tracks" "Descarga completada"
    else
        notify-send -i "$PROJECT_DIR/img/icontidal.png" "Tidal My Tracks" "Terminó con errores (código $CODE)"
    fi
fi
pausar
exit "$CODE"
