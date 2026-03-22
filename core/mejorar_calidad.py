#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║        Mejorador de Calidad de Audio en Tidal My Tracks      ║
╚══════════════════════════════════════════════════════════════╝

Para cada canción en My Tracks, busca en el catálogo de Tidal
si existe una versión de mayor calidad de audio. Si la encuentra,
agrega la mejor versión y elimina la que tenías.

INSTALACIÓN (solo la primera vez):
  pip install tidalapi

USO:
  python mejorar_calidad_tidal.py
"""

import re
import time
from collections import defaultdict

try:
    import tidalapi
except ImportError:
    tidalapi = None

# ── Configuración ─────────────────────────────────────────────────────────────

# Pausa entre llamadas a la API (segundos)
RATE_LIMIT_DELAY = 0.5

# Pausa extra después de agregar/eliminar un track
MODIFY_DELAY = 1.0

# Máximo de canciones a escanear de My Tracks.
# Aumenta este valor si tu biblioteca supera el límite.
MAX_TRACKS = 50_000

# Archivo de log
LOG_MEJORADAS = "tidal_calidad_mejorada.txt"

# Ranking de calidad de audio (mayor número = mejor)
QUALITY_RANK = {
    "HI_RES_LOSSLESS": 5,  # 24-bit/192kHz FLAC
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

# Calidades que ya son máximas: no tiene sentido buscar mejora
TOP_QUALITIES = {"HI_RES_LOSSLESS", "HI_RES"}

# Patrones de ruido para normalizar títulos al comparar resultados de búsqueda
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
    r"\b(19|20)\d{2}\b",
    r"\b\d+(st|nd|rd|th)\b",
]

NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.IGNORECASE)


# ── Utilidades ────────────────────────────────────────────────────────────────


def get_quality(track) -> str:
    q = getattr(track, "audio_quality", None)
    if q is None:
        return "UNKNOWN"
    return (q.value if hasattr(q, "value") else str(q)).upper()


def quality_rank(track) -> int:
    return QUALITY_RANK.get(get_quality(track), 0)


def qlabel(track) -> str:
    return QUALITY_LABEL.get(get_quality(track), get_quality(track))


def normalize(text: str) -> str:
    """Normaliza un texto para comparación: minúsculas, sin ruido, sin símbolos."""
    text = text.lower()
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"\[.*?\]", " ", text)
    text = NOISE_RE.sub(" ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def track_label(track) -> str:
    artist = track.artist.name if track.artist else "?"
    return f"{artist} - {track.name}"


# ── Paginación completa de My Tracks ─────────────────────────────────────────


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
    Descarga todos los tracks de My Tracks con paginación robusta.
    Para cuando la API devuelve dos páginas vacías consecutivas.
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


# ── Búsqueda de versión de mayor calidad ─────────────────────────────────────


def search_better_version(session, track):
    """
    Busca en el catálogo de Tidal una versión del mismo track con calidad superior.

    Estrategia:
      1. Busca "{artista} {título}" en la API de búsqueda.
      2. Filtra resultados que tengan el mismo artista y título normalizados.
      3. Entre los candidatos, devuelve el de mayor calidad si supera al actual.
      4. Si hay empate de calidad, prefiere el de mayor QUALITY_RANK (mismo nivel).

    Devuelve el track candidato o None si no hay mejora disponible.
    """
    artist_name = track.artist.name if track.artist else ""
    title = track.name or ""
    current_rank = quality_rank(track)

    query = f"{artist_name} {title}"
    norm_artist = normalize(artist_name)
    norm_title = normalize(title)

    try:
        results = session.search(query, models=[tidalapi.Track], limit=20)
        candidates = (
            results.get("tracks", [])
            if isinstance(results, dict)
            else getattr(results, "tracks", [])
        )
    except Exception:
        return None

    best = None
    best_rank = current_rank  # solo mejoramos si superamos el nivel actual

    for candidate in candidates:
        # Asegurar que el audio_quality viene del objeto (puede ser un enum)
        cand_q_raw = getattr(candidate, "audio_quality", None)
        if cand_q_raw is None:
            continue

        # Filtrar por artista y título normalizados
        cand_artist = candidate.artist.name if candidate.artist else ""
        cand_title = candidate.name or ""
        if normalize(cand_artist) != norm_artist:
            continue
        if normalize(cand_title) != norm_title:
            continue

        cand_rank = quality_rank(candidate)
        if cand_rank > best_rank:
            best_rank = cand_rank
            best = candidate

    return best


# ── Proceso principal ─────────────────────────────────────────────────────────


def process_tracks(session, tracks, log_entries, errors):
    """
    Recorre los tracks, detecta cuáles tienen versión de mayor calidad disponible
    y realiza el upgrade (agregar mejor + eliminar peor).

    Devuelve el número de tracks mejorados.
    """
    improved = 0
    skipped_top = 0
    total = len(tracks)

    for i, track in enumerate(tracks, 1):
        label = track_label(track)
        current_q = get_quality(track)
        current_ql = qlabel(track)

        print(f"  [{i}/{total}] {label[:55]}  [{current_ql}]", end="  ", flush=True)

        # Si ya es la calidad máxima, no hay nada que buscar
        if current_q in TOP_QUALITIES:
            print("— ya es máxima calidad, omitiendo")
            skipped_top += 1
            continue

        better = search_better_version(session, track)
        time.sleep(RATE_LIMIT_DELAY)

        if better is None:
            print("— sin mejora disponible")
            continue

        better_ql = qlabel(better)
        print(f"→ mejora encontrada [{better_ql}]", end="  ", flush=True)

        # 1. Agregar la versión de mayor calidad
        try:
            session.user.favorites.add_track(better.id)
            time.sleep(MODIFY_DELAY)
        except Exception as e:
            print(f"⚠️  Error al agregar: {e}")
            errors.append(f"ADD FAIL | {label} → [{better_ql}]: {e}")
            continue

        # 2. Eliminar la versión de menor calidad
        try:
            session.user.favorites.remove_track(track.id)
            time.sleep(MODIFY_DELAY)
            print("✅")
            log_entries.append(
                f"MEJORADA: {label}\n"
                f"  Antes : [{current_ql}]  ID={track.id}\n"
                f"  Ahora : [{better_ql}]   ID={better.id}  ({better.name})"
            )
            improved += 1
        except Exception as e:
            print(f"⚠️  Error al eliminar original: {e}")
            errors.append(f"REMOVE FAIL | {label}: {e}")
            # La mejor versión ya se agregó; el original queda como duplicado
            # (el script de duplicados puede limpiarlo después)

    return improved, skipped_top


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    if tidalapi is None:
        print("❌ tidalapi no está instalado.")
        print("   Ejecuta en tu terminal:  pip install tidalapi")
        return

    print("=" * 62)
    print("    Mejorador de Calidad de Audio — Tidal My Tracks")
    print("=" * 62)

    # ── 1. Autenticación ──────────────────────────────────────────
    print("\n[1/4] Conectando con Tidal (se abrirá tu navegador)...")
    session = tidalapi.Session()
    try:
        session.login_oauth_simple()
    except Exception as e:
        print(f"❌ No se pudo conectar: {e}")
        return
    print("✅ Sesión iniciada correctamente")

    # ── 2. Descargar My Tracks ────────────────────────────────────
    print("\n[2/4] Descargando tu lista completa de My Tracks...")
    try:
        tracks = get_all_tracks(session)
    except Exception as e:
        print(f"❌ Error: {e}")
        return
    print(f"  📋 {len(tracks)} canciones descargadas")

    # ── 3. Vista previa de distribución de calidad ────────────────
    print("\n[3/4] Distribución de calidad actual:")
    quality_dist: dict[str, int] = defaultdict(int)
    for t in tracks:
        quality_dist[qlabel(t)] += 1
    for ql, count in sorted(
        quality_dist.items(),
        key=lambda x: -QUALITY_RANK.get(
            next((k for k, v in QUALITY_LABEL.items() if v == x[0]), ""), 0
        ),
    ):
        print(f"       {ql:<22} : {count} canciones")

    already_top = sum(1 for t in tracks if get_quality(t) in TOP_QUALITIES)
    upgradeable = len(tracks) - already_top
    print(f"\n  ℹ️  {already_top} ya en calidad máxima (se omitirán)")
    print(f"  🔍 {upgradeable} canciones a verificar en el catálogo\n")

    if upgradeable == 0:
        print("✅ ¡Toda tu biblioteca ya está en la calidad más alta disponible!")
        return

    confirm = (
        input("¿Iniciar búsqueda y mejora automática? Escribe 'si': ").strip().lower()
    )
    if confirm not in ("si", "sí", "yes", "s", "y"):
        print("❌ Cancelado.")
        return

    # ── 4. Procesar tracks ────────────────────────────────────────
    print("\n[4/4] Procesando canciones...\n")
    log_entries = []
    errors = []

    improved, skipped_top = process_tracks(session, tracks, log_entries, errors)

    # ── Resumen final ─────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("  RESUMEN FINAL")
    print("=" * 62)
    print(f"  🎵 Canciones procesadas  : {len(tracks)}")
    print(f"  ⏭️  Ya en calidad máxima  : {skipped_top}")
    print(f"  ✅ Mejoradas             : {improved}")
    print(f"  ⚠️  Errores              : {len(errors)}")

    if log_entries:
        try:
            logs_dir = Path(__file__).parent.parent / "logs"
            logs_dir.mkdir(exist_ok=True)
            with open(logs_dir / LOG_MEJORADAS, "a", encoding="utf-8") as f:
                f.write("\n\n".join(log_entries) + "\n")
            print(f"\n  💾 Log guardado en: logs/{LOG_MEJORADAS}")
        except Exception:
            pass

    if errors:
        print("\n  Errores detallados:")
        for e in errors:
            print(f"    • {e}")

    print("\n✅ ¡Proceso completado!")
    if improved > 0:
        print(
            "   Tip: ejecuta limpiar_duplicados_tidal.py para eliminar\n"
            "   cualquier copia residual que haya quedado."
        )


if __name__ == "__main__":
    main()
