#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║        Sincronizador de Música Local → Tidal My Tracks       ║
╚══════════════════════════════════════════════════════════════╝

Busca cada canción de tu carpeta local en el catálogo de Tidal
y la agrega a "My Tracks" si no la tienes ya.

INSTALACIÓN (ejecuta esto en tu terminal primero):
  pip install tidalapi

USO:
  python sincronizar_tidal.py

  Se abrirá tu navegador para que inicies sesión en Tidal.
  Luego el script trabaja solo.
"""

import os
import re
import time
import json
from pathlib import Path

try:
    import tidalapi
except ImportError:
    tidalapi = None

# ================================================================
#  CONFIGURACIÓN — Cambia MUSIC_DIR a la ruta de tu carpeta
# ================================================================

# Ejemplos:
#   Windows : r"C:\Users\TuNombre\Music\Telegram"
#   Mac     : "/Users/TuNombre/Music/Telegram"
#   Linux   : "/home/TuNombre/Music/Telegram"

MUSIC_DIR = r""

# Pausa entre búsquedas (segundos). Sube a 1.0 si ves errores de rate limit.
RATE_LIMIT_DELAY = 0.5

# Máximo de canciones a leer de My Tracks en Tidal (para verificar existencia).
# Aumenta este valor si tu biblioteca supera el límite.
MAX_TRACKS = 50_000

# Archivos de log
LOG_AGREGADAS = "tidal_agregadas.txt"
LOG_NO_ENCONTRADAS = "tidal_no_encontradas.txt"
LOG_YA_EXISTIAN = "tidal_ya_existian.txt"

# ================================================================

AUDIO_EXTENSIONS = {".flac", ".mp3", ".wav", ".m4a", ".ogg", ".aac", ".opus"}


def get_songs_from_folder(music_dir: str) -> list[tuple[str, str, str]]:
    """
    Lee todos los archivos de audio en las subcarpetas de artista.
    Devuelve lista de (artista, titulo, nombre_archivo).
    """
    songs = []
    music_path = Path(music_dir)

    if not music_path.exists():
        print(f"❌ No se encontró la carpeta: {music_dir}")
        print("   Edita el script y asegúrate de que MUSIC_DIR sea correcto.")
        return songs

    for artist_folder in sorted(music_path.iterdir()):
        if not artist_folder.is_dir():
            continue
        if artist_folder.name in ("Sin clasificar", "__pycache__"):
            continue

        skipped_format = []
        for song_file in sorted(artist_folder.iterdir()):
            if song_file.suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            stem = song_file.stem  # nombre sin extensión
            if " - " in stem:
                parts = stem.split(" - ", 1)
                artist = parts[0].strip()
                title = parts[1].strip()
                songs.append((artist, title, song_file.name))
            else:
                skipped_format.append(song_file.name)

        if skipped_format:
            print(
                f"  ⚠️  {len(skipped_format)} archivo(s) en '{artist_folder.name}' "
                f"omitidos por no seguir el formato 'Artista - Título':"
            )
            for name in skipped_format[:5]:
                print(f"       • {name}")
            if len(skipped_format) > 5:
                print(f"       ... y {len(skipped_format) - 5} más.")

    return songs


def normalize(text: str) -> str:
    """Normaliza texto para comparación."""
    text = text.lower()
    text = re.sub(r"\(.*?\)", "", text)  # quita paréntesis y contenido
    text = re.sub(r"\[.*?\]", "", text)  # quita corchetes
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def find_best_match(results_tracks, artist: str, title: str):
    """Elige el track de Tidal que mejor corresponde al artista y título locales."""
    artist_norm = normalize(artist)
    title_norm = normalize(title)

    for track in results_tracks[:10]:
        tidal_artist = track.artist.name if track.artist else ""
        tidal_title = track.name or ""

        ta = normalize(tidal_artist)
        tt = normalize(tidal_title)

        # Match exacto o contenido
        artist_match = (artist_norm in ta) or (ta in artist_norm)
        title_match = (title_norm in tt) or (tt in title_norm)

        if artist_match and title_match:
            return track

    # Sin match exacto → no agregar para evitar canciones incorrectas
    return None


def search_track(session, artist: str, title: str):
    """Busca un track en Tidal y devuelve el mejor match o None."""
    query = f"{artist} {title}"
    try:
        results = session.search(query, models=[tidalapi.Track], limit=20)
        tracks = results.get("tracks", [])
        if tracks:
            return find_best_match(tracks, artist, title)
    except Exception as e:
        print(f"\n  ⚠️  Error buscando '{query}': {e}")
    return None


def main():
    # Verificar que MUSIC_DIR está configurado
    if not MUSIC_DIR:
        print("⚠️  Falta configurar MUSIC_DIR en el script.")
        print(
            "   Abre sincronizar_tidal.py y pon la ruta completa a tu carpeta de música."
        )
        print('\n   Ejemplo Mac/Linux : MUSIC_DIR = "/Users/Claudia/Music/Telegram"')
        print(
            '   Ejemplo Windows   : MUSIC_DIR = r"C:\\Users\\Claudia\\Music\\Telegram"'
        )
        return

    # Verificar que tidalapi está instalado
    if tidalapi is None:
        print("❌ tidalapi no está instalado.")
        print("   Ejecuta en tu terminal:  pip install tidalapi")
        return

    print("=" * 62)
    print("    Sincronizador de Música Local → Tidal My Tracks")
    print("=" * 62)

    # ── 1. Autenticación ─────────────────────────────────────────
    print("\n[1/4] Conectando con Tidal (se abrirá tu navegador)...")
    session = tidalapi.Session()
    try:
        session.login_oauth_simple()
    except Exception as e:
        print(f"❌ No se pudo conectar: {e}")
        return
    print(f"✅ Sesión iniciada correctamente")

    # ── 2. Favoritos actuales (paginación completa) ───────────────
    print("\n[2/4] Leyendo tu My Tracks actual en Tidal...")
    try:
        existing_ids = set()
        offset = 0
        limit = 100
        total_label = "?"
        consecutive_empty = 0
        while True:
            r = session.request.request(
                "GET",
                f"users/{session.user.id}/favorites/tracks",
                params={
                    "limit": limit,
                    "offset": offset,
                    "countryCode": session.country_code,
                },
            )
            data = r.json()
            raw_total = data.get("totalNumberOfItems")
            if raw_total is not None:
                try:
                    total_label = int(raw_total)
                except (ValueError, TypeError):
                    pass
            items = data.get("items", [])
            # Solo las páginas sin items JSON cuentan como "vacías" reales.
            if not items:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
                offset += limit
                continue
            # Hay items → resetear contador y procesar
            consecutive_empty = 0
            for item in items:
                track_data = item.get("item")
                if track_data:
                    existing_ids.add(track_data.get("id"))
            print(
                f"  Leyendo favoritos: {len(existing_ids)}/{total_label} (offset={offset})...",
                end="\r",
                flush=True,
            )
            if len(existing_ids) >= MAX_TRACKS:
                print(f"\n  ⚠️  Límite de {MAX_TRACKS} canciones alcanzado.")
                break
            offset += limit
        print()
        print(f"✅ Tienes {len(existing_ids)} canciones en My Tracks")
    except Exception as e:
        print(f"⚠️  No se pudieron obtener favoritos: {e}")
        existing_ids = set()

    # ── 3. Leer archivos locales ──────────────────────────────────
    print(f"\n[3/4] Leyendo canciones de:\n  {MUSIC_DIR}")
    songs = get_songs_from_folder(MUSIC_DIR)
    if not songs:
        print("❌ No se encontraron canciones. Verifica la ruta.")
        return
    print(f"✅ {len(songs)} canciones encontradas localmente")

    # ── 4. Buscar y agregar ───────────────────────────────────────
    print(f"\n[4/4] Buscando en Tidal y agregando a My Tracks...\n")

    added = []
    not_found = []
    already_exists = []
    errors = []

    for i, (artist, title, filename) in enumerate(songs, 1):
        label = f"{artist} - {title}"
        print(f"[{i:>4}/{len(songs)}] {label[:60]:<60}", end=" ", flush=True)

        track = search_track(session, artist, title)

        if track is None:
            print("❌ No encontrada")
            not_found.append(label)

        elif track.id in existing_ids:
            print("✓  Ya existe")
            already_exists.append(label)

        else:
            try:
                session.user.favorites.add_track(track.id)
                existing_ids.add(track.id)
                tidal_label = (
                    f"{track.artist.name} - {track.name}"
                    if track.artist
                    else track.name
                )
                print(f"➕ Agregada  [{tidal_label[:45]}]")
                added.append(f"{label}  →  {tidal_label}")
            except Exception as e:
                print(f"⚠️  Error: {e}")
                errors.append(f"{label}: {e}")

        time.sleep(RATE_LIMIT_DELAY)

    # ── Resumen ───────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  RESUMEN FINAL")
    print("=" * 62)
    print(f"  ➕ Canciones nuevas agregadas a My Tracks : {len(added)}")
    print(f"  ✓  Ya existían en My Tracks               : {len(already_exists)}")
    print(f"  ❌ No encontradas en catálogo de Tidal     : {len(not_found)}")
    print(f"  ⚠️  Errores                                : {len(errors)}")

    # Guardar logs
    script_dir = Path(__file__).parent

    if added:
        with open(script_dir / LOG_AGREGADAS, "a", encoding="utf-8") as f:
            f.write("\n".join(added) + "\n")
        print(f"\n  💾 Canciones agregadas  → {LOG_AGREGADAS}")

    if not_found:
        with open(script_dir / LOG_NO_ENCONTRADAS, "a", encoding="utf-8") as f:
            f.write("\n".join(not_found) + "\n")
        print(f"  💾 No encontradas       → {LOG_NO_ENCONTRADAS}")

    if already_exists:
        with open(script_dir / LOG_YA_EXISTIAN, "a", encoding="utf-8") as f:
            f.write("\n".join(already_exists) + "\n")
        print(f"  💾 Ya existían          → {LOG_YA_EXISTIAN}")

    print("\n✅ ¡Proceso completado!")


if __name__ == "__main__":
    main()
