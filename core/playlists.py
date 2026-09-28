"""
Descarga una playlist de Tidal a la biblioteca plana y genera su .m3u8.

Solo se descargan las pistas cuyo ISRC no está ya en <base>/canciones; el
resto se reutiliza. La descarga usa el mismo flujo que My Tracks (tiddl,
aplanado y mejora a Hi-Res).

Genera dos listas con el orden de Tidal:
  <base>/playlists/<nombre>.m3u8           rutas ../canciones/<archivo> (laptop)
  <base>/playlists/plana/<nombre>.m3u8     solo <archivo>, para una carpeta
                                           plana como Download/Quick Share del
                                           teléfono (la lista va junto a las
                                           canciones)

Uso: python -m core.playlists "Reggaeton viejito" [carpeta]
"""

import re
import sys
import unicodedata
from pathlib import Path

from core import biblioteca, hires
from core.descargar import DEFAULT_OUTPUT_DIR, _descargar


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().casefold()


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def _todas(s) -> dict:
    """Playlists propias y favoritas, sin repetir, por ID."""
    vistas = {}
    for p in s.user.playlists() + s.user.favorites.playlists():
        vistas.setdefault(p.id, p)
    return vistas


def listar_playlists() -> list[dict] | None:
    """[{id, name, tracks}] ordenadas por nombre, o None si falta la sesión PKCE."""
    s = hires.sesion()
    if s is None:
        return None
    return sorted(({"id": p.id, "name": p.name.strip(), "tracks": p.num_tracks}
                   for p in _todas(s).values()), key=lambda d: _normalizar(d["name"]))


def _buscar_playlist(s, nombre: str):
    """
    Playlist por ID/URL (UUID) o por nombre de una propia o favorita
    (sin acentos ni mayúsculas).
    """
    uuid = _UUID.search(nombre)
    if uuid:
        try:
            return s.playlist(uuid.group(0))
        except Exception:
            return None
    buscado = _normalizar(nombre)
    vistas = _todas(s)
    exactas = [p for p in vistas.values() if _normalizar(p.name) == buscado]
    if exactas:
        return exactas[0]
    parecidas = [p for p in vistas.values() if buscado in _normalizar(p.name)]
    return parecidas[0] if len(parecidas) == 1 else None


def _archivos_por_isrc(base: Path) -> dict[str, Path]:
    """ISRC → archivo en canciones/. Se prefiere la versión estéreo (FLAC) a la Atmos."""
    resultado: dict[str, Path] = {}
    carpeta = base / biblioteca.CANCIONES
    if not carpeta.is_dir():
        return resultado
    for p in sorted(carpeta.iterdir(), key=lambda x: (x.suffix != ".flac", x.name)):
        if p.suffix in biblioteca.AUDIO_EXT:
            isrc = (biblioteca._tags(p).get("isrc") or "").upper()
            if isrc and isrc not in resultado:
                resultado[isrc] = p
    return resultado


def _nombre_archivo(nombre: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "-", nombre).strip()


def _escribir_m3u(destino: Path, entradas: list[tuple[str, str, int]]) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    lineas = ["#EXTM3U"]
    for titulo, ruta, duracion in entradas:
        lineas.append(f"#EXTINF:{duracion},{titulo}")
        lineas.append(ruta)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def descargar_playlist(nombre: str, output_dir: str = ""):
    """
    Generador (para SSE): descarga lo que falta de la playlist y escribe sus
    .m3u8. Devuelve el código de salida.
    """
    base = Path(output_dir or DEFAULT_OUTPUT_DIR).expanduser()
    s = hires.sesion()
    if s is None:
        yield "❌ Falta la sesión de Tidal (PKCE). Ejecuta: .venv/bin/python -m core.hires login"
        return 1

    playlist = _buscar_playlist(s, nombre)
    if playlist is None:
        yield f"❌ No encontré la playlist «{nombre}» en tu cuenta"
        return 1

    pistas = list(playlist.tracks_paginated())
    yield f"▶ Playlist «{playlist.name}»: {len(pistas)} pistas"

    locales = _archivos_por_isrc(base)
    pendientes = [t for t in pistas
                  if (t.isrc or "").upper() not in locales and getattr(t, "available", True)]
    no_disponibles = [t for t in pistas if not getattr(t, "available", True)]
    yield (f"📋 {len(pistas) - len(pendientes) - len(no_disponibles)} ya descargadas, "
           f"{len(pendientes)} por descargar, {len(no_disponibles)} no disponibles en Tidal")

    # hires.mejorar busca el ID de Tidal por ISRC en este registro
    registro = biblioteca._cargar_registro(base)
    for t in pistas:
        if t.isrc:
            registro.setdefault(str(t.id), t.isrc.upper())
    biblioteca._guardar_registro(base, registro)

    code = 0
    if pendientes:
        code = yield from _descargar(["url", *(f"track/{t.id}" for t in pendientes)], str(base))
        locales = _archivos_por_isrc(base)

    laptop, plana, faltan = [], [], []
    for t in pistas:
        archivo = locales.get((t.isrc or "").upper())
        if archivo is None:
            faltan.append(t)
            continue
        titulo = f"{t.artist.name} - {t.name}" if t.artist else t.name
        laptop.append((titulo, f"../{biblioteca.CANCIONES}/{archivo.name}", int(t.duration or -1)))
        plana.append((titulo, archivo.name, int(t.duration or -1)))

    nombre_m3u = _nombre_archivo(playlist.name) + ".m3u8"
    _escribir_m3u(base / "playlists" / nombre_m3u, laptop)
    _escribir_m3u(base / "playlists" / "plana" / nombre_m3u, plana)
    yield f"📝 Lista con {len(laptop)} canciones → {base / 'playlists' / nombre_m3u}"
    ids_no_disp = {t.id for t in no_disponibles}
    for t in faltan:
        motivo = "no disponible en Tidal" if t.id in ids_no_disp else "sin archivo"
        yield f"   ⚠ {t.name} ({t.id}): {motivo}"
    # Las no disponibles no cuentan como error: no hay forma de descargarlas
    return code or (1 if any(t.id not in ids_no_disp for t in faltan) else 0)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Uso: python -m core.playlists "Nombre de la playlist" [carpeta]')
    gen = descargar_playlist(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
    try:
        while True:
            print(next(gen), flush=True)
    except StopIteration as fin:
        sys.exit(fin.value or 0)
