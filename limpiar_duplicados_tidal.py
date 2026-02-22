#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         Limpiador de Duplicados en Tidal My Tracks           ║
╚══════════════════════════════════════════════════════════════╝

Revisa tu lista de My Tracks en Tidal, detecta canciones
repetidas y elimina los duplicados conservando una sola copia.

INSTALACIÓN (solo la primera vez):
  pip install tidalapi

USO:
  python limpiar_duplicados_tidal.py
"""

import re
import time
from collections import defaultdict

# Pausa entre eliminaciones para no saturar la API
RATE_LIMIT_DELAY = 0.3

# Cuántos tracks traer por página
PAGE_SIZE = 100

# Máximo de canciones a escanear de My Tracks.
# Aumenta este valor si tu biblioteca supera el límite.
MAX_TRACKS = 50_000

# Archivo de log con lo que se eliminó
LOG_ELIMINADOS = "tidal_duplicados_eliminados.txt"

try:
    import tidalapi
except ImportError:
    tidalapi = None

# Palabras y patrones que se ignoran al comparar títulos
# (versiones alternativas de la misma canción)
NOISE_PATTERNS = [
    r"\bremaster(?:ed)?\b",
    r"\banniversary\b",
    r"\bdeluxe\b",
    r"\bbonus\b",
    r"\balbum version\b",
    r"\bsingle version\b",
    r"\bradio edit\b",
    r"\boriginal\b",
    r"\bexplicit\b",
    r"\bclean\b",
    r"\blive\b",
    r"\bacoustic\b",
    r"\bmono\b",
    r"\bstereo\b",
    r"\bdigital remaster\b",
    r"\brevisited\b",
    r"\bexpanded\b",
    r"\bspecial edition\b",
    r"\b(19|20)\d{2}\b",  # años como 2011, 1999, etc.
    r"\b\d+(st|nd|rd|th)\b",  # 25th, 1st, etc.
]

NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE)

# Ranking de calidad de audio (mayor número = mejor calidad)
QUALITY_RANK = {
    "HI_RES_LOSSLESS": 5,  # hasta 24-bit/192kHz FLAC
    "HI_RES": 4,  # MQA
    "LOSSLESS": 3,  # FLAC 16-bit/44.1kHz
    "HIGH": 2,  # 320 kbps AAC
    "LOW": 1,  # 96 kbps AAC
}

QUALITY_LABEL = {
    "HI_RES_LOSSLESS": "Hi-Res Lossless",
    "HI_RES": "Hi-Res (MQA)",
    "LOSSLESS": "Lossless (FLAC)",
    "HIGH": "High (320kbps)",
    "LOW": "Low (96kbps)",
}

# ── Patrones de detección de variantes ────────────────────────────────────────
# Cada patrón devuelve True si el texto del track/álbum contiene ese rasgo.
_RE_REMASTER = re.compile(r"\b(?:remaster(?:ed)?|digital remaster)\b", re.I)
_RE_EXPLICIT = re.compile(r"\bexplicit\b", re.I)
_RE_CLEAN = re.compile(r"\bclean\b", re.I)
_RE_STEREO = re.compile(r"\bstereo\b", re.I)
_RE_MONO = re.compile(r"\bmono\b", re.I)
_RE_ALBUM_VER = re.compile(r"\balbum version\b", re.I)
_RE_SINGLE_VER = re.compile(r"\bsingle version\b", re.I)
_RE_YEAR = re.compile(r"\b(19|20)(\d{2})\b")


def _tag(track) -> str:
    """Combina título + nombre del álbum para detectar variantes."""
    title = track.name or ""
    album = (track.album.name if track.album else "") or ""
    return f"{title} {album}"


def _remaster_year(track) -> int:
    """
    Extrae el año del remaster (p.ej. 'Remastered 2011' → 2011).
    Si no hay año devuelve 0 (remaster sin año = más antiguo).
    """
    tag = _tag(track)
    if not _RE_REMASTER.search(tag):
        return -1  # no es remaster
    m = _RE_YEAR.search(tag)
    return int(m.group(0)) if m else 0


def version_priority(track) -> tuple:
    """
    Tupla de criterios de desempate (todos descendentes: mayor = mejor).

    Orden de prioridad cuando la calidad de audio es igual:
      1. Remaster reciente > remaster antiguo > sin remaster
      2. Explicit > Clean
      3. Stereo > Mono
      4. Album version > Single version
      5. ID más bajo (original histórico en Tidal)
    """
    tag = _tag(track)

    # 1. Remaster: año del remaster (−1 si no es remaster, 0 si año desconocido)
    remaster_score = _remaster_year(track)

    # 2. Explicit (1) > Clean (0) — si es clean penaliza
    explicit_score = (
        1 if _RE_EXPLICIT.search(tag) else (0 if not _RE_CLEAN.search(tag) else -1)
    )

    # 3. Stereo (1) > sin indicación (0) > Mono (-1)
    if _RE_STEREO.search(tag):
        stereo_score = 1
    elif _RE_MONO.search(tag):
        stereo_score = -1
    else:
        stereo_score = 0

    # 4. Album version (1) > sin indicación (0) > Single version (-1)
    if _RE_ALBUM_VER.search(tag):
        album_score = 1
    elif _RE_SINGLE_VER.search(tag):
        album_score = -1
    else:
        album_score = 0

    # 5. ID menor = más antiguo/original en Tidal (valor positivo: menor ID es mejor)
    id_score = getattr(track, "id", 0)

    return (remaster_score, explicit_score, stereo_score, album_score, id_score)


def get_quality(track) -> str:
    """Devuelve el string de calidad del track (normalizado a mayúsculas)."""
    q = getattr(track, "audio_quality", None)
    if q is None:
        return "UNKNOWN"
    return (q.value if hasattr(q, "value") else str(q)).upper()


def quality_rank(track) -> int:
    return QUALITY_RANK.get(get_quality(track), 0)


def normalize(text: str) -> str:
    """
    Normaliza texto para comparación minuciosa:
    - Minúsculas
    - Elimina contenido entre paréntesis y corchetes
    - Elimina palabras de 'ruido' (Remastered, Anniversary, Live, etc.)
    - Elimina años y números de edición
    - Elimina símbolos, deja solo letras y números
    """
    text = text.lower()
    text = re.sub(r"\(.*?\)", " ", text)  # quita (contenido)
    text = re.sub(r"\[.*?\]", " ", text)  # quita [contenido]
    text = NOISE_RE.sub(" ", text)  # quita palabras de ruido
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def _parse_track_safe(session, track_data):
    """
    Intenta parsear el track con tidalapi. Si falla (tracks con datos
    incompletos, restricciones de región, etc.), construye un objeto mínimo
    directamente del JSON para no perder la canción.
    """
    try:
        return session.parse_track(track_data)
    except Exception:
        pass

    class _T:
        pass

    t = _T()
    t.id = track_data.get("id")
    t.name = track_data.get("title") or track_data.get("name") or "?"
    a = track_data.get("artist") or {}
    t.artist = _T()
    t.artist.name = (a.get("name") or "?") if isinstance(a, dict) else "?"
    alb = track_data.get("album") or {}
    t.album = _T()
    t.album.name = (
        (alb.get("title") or alb.get("name") or "?") if isinstance(alb, dict) else "?"
    )
    t.audio_quality = track_data.get("audioQuality") or track_data.get("audio_quality")
    return t


def get_all_tracks(session):
    """
    Obtiene TODOS los tracks de My Tracks usando llamadas directas a la API
    de Tidal con paginación explícita por offset.

    Condición de parada: la API devuelve una página vacía (sin items), lo que
    indica que se agotaron todos los registros. No se confía en totalNumberOfItems
    ni en el tamaño de página para cortar el loop, ya que ambos pueden ser
    menores al esperado sin significar el fin real de la lista.
    """
    all_tracks = []
    seen_ids = set()
    skipped_unavailable = 0  # tracks con item=null: eliminados del catálogo de Tidal
    offset = 0
    limit = 100
    total_label = "?"
    consecutive_empty = 0

    while True:
        try:
            r = session.request.request(
                "GET",
                f"users/{session.user.id}/favorites/tracks",
                params={
                    "limit": limit,
                    "offset": offset,
                    "order": "DATE",
                    "orderDirection": "DESC",
                    "countryCode": session.country_code,
                },
            )
            data = r.json()
        except Exception as e:
            print(f"\n  ❌ Error en paginación (offset={offset}): {e}")
            break

        raw_total = data.get("totalNumberOfItems")
        if raw_total is not None:
            try:
                total_label = int(raw_total)
            except (ValueError, TypeError):
                pass

        items = data.get("items", [])

        # Solo las páginas sin items JSON cuentan como "vacías" reales.
        # Los fallos de parse no cortan el loop (pueden ser episodios, videos, etc.)
        if not items:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
            offset += limit
            continue

        # Hay items en el JSON → resetear contador y procesar
        consecutive_empty = 0

        for item in items:
            track_data = item.get("item")
            if not track_data:
                skipped_unavailable += 1  # sin datos: track eliminado del catálogo
                continue
            track_id = track_data.get("id")
            if not track_id or track_id in seen_ids:
                continue
            track = _parse_track_safe(session, track_data)
            if track.id is None:
                continue
            raw_q = track_data.get("audioQuality") or track_data.get("audio_quality")
            if raw_q:
                track.audio_quality = raw_q
            seen_ids.add(track_id)
            all_tracks.append(track)

        print(
            f"  Descargados {len(all_tracks)}/{total_label} tracks (offset={offset})...",
            end="\r",
            flush=True,
        )

        # Límite de seguridad absoluto (nunca leer más de MAX_TRACKS)
        if len(all_tracks) >= MAX_TRACKS:
            print(f"\n  ⚠️  Límite de {MAX_TRACKS} canciones alcanzado.")
            break

        offset += limit

    print()
    if skipped_unavailable:
        print(
            f"  ℹ️  {skipped_unavailable} tracks con item=null: "
            f"eliminados del catálogo de Tidal o no disponibles en tu región"
        )
    if isinstance(total_label, int):
        missing = total_label - len(all_tracks) - skipped_unavailable
        if missing > 0:
            print(
                f"  ℹ️  {missing} tracks que Tidal reporta en el total ({total_label}) "
                f"no aparecieron en ninguna página de la API "
                f"(borrados o restringidos por región)."
            )
    return all_tracks


def find_duplicates(tracks):
    """
    Agrupa tracks por (artista normalizado, título normalizado).

    Criterio de ordenación dentro de cada grupo (descendente = mejor primero):
      1. Calidad de audio (HI_RES_LOSSLESS > HI_RES > LOSSLESS > HIGH > LOW)
      2. Año del remaster (remaster más reciente gana sobre uno antiguo)
      3. Explicit > sin indicación > Clean
      4. Stereo > sin indicación > Mono
      5. Album version > sin indicación > Single version
      6. ID menor (versión más histórica en Tidal)

    group[0] siempre es el track que se conserva.
    Devuelve solo los grupos con más de un track.
    """
    groups = defaultdict(list)

    for track in tracks:
        artist = track.artist.name if track.artist else "desconocido"
        title = track.name or ""
        key = (normalize(artist), normalize(title))
        groups[key].append(track)

    duplicates = {}
    for k, v in groups.items():
        if len(v) > 1:

            def sort_key(t):
                qr = quality_rank(t)
                # version_priority devuelve (remaster_year, explicit, stereo, album, id)
                # todos "mayor = mejor"; negamos para que sort() los ordene descendente
                vp = version_priority(t)
                return (-qr, -vp[0], -vp[1], -vp[2], -vp[3], vp[4])

            v.sort(key=sort_key)
            duplicates[k] = v

    return duplicates


def remove_duplicates_round(session, round_num, all_removed, all_errors):
    """
    Ejecuta una pasada completa: descarga lista, detecta y elimina duplicados.
    Devuelve cuántos eliminó en esta ronda.
    """
    print(f"\n{'─' * 62}")
    print(f"  RONDA {round_num} — Leyendo My Tracks...")
    print(f"{'─' * 62}")

    try:
        tracks = get_all_tracks(session)
        print(f"  📋 {len(tracks)} canciones en My Tracks")
    except Exception as e:
        print(f"  ❌ Error al leer My Tracks: {e}")
        return 0

    duplicates = find_duplicates(tracks)

    if not duplicates:
        return 0

    total = sum(len(v) - 1 for v in duplicates.values())
    print(
        f"  ⚠️  {len(duplicates)} grupos duplicados detectados → {total} copias a eliminar\n"
    )

    eliminated = 0
    for (_, _), group in duplicates.items():
        keeper = group[0]
        extras = group[1:]
        keeper_label = (
            f"{keeper.artist.name} - {keeper.name}" if keeper.artist else keeper.name
        )
        keeper_q = QUALITY_LABEL.get(get_quality(keeper), get_quality(keeper))

        for track in extras:
            t_label = (
                f"{track.artist.name} - {track.name}" if track.artist else track.name
            )
            t_q = QUALITY_LABEL.get(get_quality(track), get_quality(track))
            print(f"  ✗ {t_label[:48]} [{t_q}]", end=" ... ", flush=True)
            try:
                session.user.favorites.remove_track(track.id)
                print("✅")
                all_removed.append(
                    f"[Ronda {round_num}] ELIMINADA: {t_label} [{t_q}]"
                    f"  →  CONSERVADA: {keeper_label} [{keeper_q}]"
                )
                eliminated += 1
            except Exception as e:
                print(f"⚠️  Error: {e}")
                all_errors.append(f"{t_label}: {e}")
            time.sleep(RATE_LIMIT_DELAY)

    return eliminated


def main():
    if tidalapi is None:
        print("❌ tidalapi no está instalado.")
        print("   Ejecuta en tu terminal:  pip install tidalapi")
        return

    print("=" * 62)
    print("    Limpiador de Duplicados en Tidal My Tracks")
    print("=" * 62)

    # ── 1. Autenticación (solo una vez) ───────────────────────────
    print("\n[1/3] Conectando con Tidal (se abrirá tu navegador)...")
    session = tidalapi.Session()
    try:
        session.login_oauth_simple()
    except Exception as e:
        print(f"❌ No se pudo conectar: {e}")
        return
    print("✅ Sesión iniciada correctamente")

    # ── 2. Vista previa rápida y confirmación ─────────────────────
    print("\n[2/3] Escaneando para mostrar una vista previa...")
    try:
        tracks = get_all_tracks(session)
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    duplicates = find_duplicates(tracks)

    if not duplicates:
        print("✅ ¡No hay duplicados! Tu lista ya está limpia.")
        return

    total_to_remove = sum(len(v) - 1 for v in duplicates.values())
    print(f"\n  ⚠️  Se encontraron {len(duplicates)} grupos de canciones repetidas.")
    print(f"     (pueden aparecer más en rondas siguientes al actualizarse la lista)\n")

    print("  Vista previa (primeros 10 grupos):")
    for (_, _), group in list(duplicates.items())[:10]:
        keeper = group[0]
        keeper_label = (
            f"{keeper.artist.name} - {keeper.name}" if keeper.artist else keeper.name
        )
        keeper_q = QUALITY_LABEL.get(get_quality(keeper), get_quality(keeper))
        keeper_album = keeper.album.name if keeper.album else "?"
        print(f"  ✓ Conservar : {keeper_label}  [{keeper_q}]  (álbum: {keeper_album})")
        for t in group[1:]:
            t_label = f"{t.artist.name} - {t.name}" if t.artist else t.name
            t_q = QUALITY_LABEL.get(get_quality(t), get_quality(t))
            t_album = t.album.name if t.album else "?"
            print(f"  ✗ Eliminar  : {t_label}  [{t_q}]  (álbum: {t_album})")
        print()

    if len(duplicates) > 10:
        print(f"  ... y {len(duplicates) - 10} grupos más.\n")

    confirm = (
        input(
            "¿Eliminar todos los duplicados automáticamente hasta limpiar la lista? Escribe 'si': "
        )
        .strip()
        .lower()
    )
    if confirm not in ("si", "sí", "yes", "s", "y"):
        print("❌ Cancelado. No se eliminó nada.")
        return

    # ── 3. Bucle hasta que no queden duplicados ───────────────────
    print("\n[3/3] Iniciando limpieza automática por rondas...\n")

    all_removed = []
    all_errors = []
    round_num = 1

    while True:
        eliminated = remove_duplicates_round(
            session, round_num, all_removed, all_errors
        )

        if eliminated == 0:
            print(
                f"\n  ✅ Ronda {round_num}: sin duplicados detectados. ¡Lista limpia!"
            )
            break

        print(
            f"\n  ✅ Ronda {round_num} completada: {eliminated} duplicados eliminados."
        )
        print("     Esperando 3 segundos para que Tidal actualice la lista...")
        time.sleep(3)
        round_num += 1

    # ── Resumen final ─────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  RESUMEN FINAL")
    print("=" * 62)
    print(f"  🔁 Rondas ejecutadas     : {round_num}")
    print(f"  ✅ Total eliminados      : {len(all_removed)}")
    print(f"  ⚠️  Errores              : {len(all_errors)}")

    if all_removed:
        try:
            with open(LOG_ELIMINADOS, "a", encoding="utf-8") as f:
                f.write("\n".join(all_removed) + "\n")
            print(f"\n  💾 Log guardado en: {LOG_ELIMINADOS}")
        except Exception:
            pass

    print("\n✅ ¡Tu My Tracks está completamente limpio!")


if __name__ == "__main__":
    main()
