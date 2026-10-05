"""
Playlists de la cuenta y sus listas .m3u8.

La descarga en sí está en core/recursos.py (igual para canciones, álbumes,
playlists, mixes y My Tracks). Aquí se generan dos listas con el orden de Tidal:
  <base>/playlists/<nombre>.m3u8           rutas ../canciones/<archivo> (laptop)
  <base>/playlists/plana/<nombre>.m3u8     solo <archivo>, para una carpeta
                                           plana como Download/Quick Share del
                                           teléfono (la lista va junto a las
                                           canciones)
"""

import re
import unicodedata
from pathlib import Path

from core import biblioteca, sesion


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().casefold()



def _todas(s) -> dict:
    """Playlists propias y favoritas, sin repetir, por ID."""
    vistas = {}
    for p in s.user.playlists() + s.user.favorites.playlists():
        vistas.setdefault(p.id, p)
    return vistas


def listar_playlists() -> list[dict] | None:
    """[{id, name, tracks}] ordenadas por nombre, o None si falta la sesión PKCE."""
    s = sesion.sesion()
    if s is None:
        return None
    return sorted(({"id": p.id, "name": p.name.strip(), "tracks": p.num_tracks}
                   for p in _todas(s).values()), key=lambda d: _normalizar(d["name"]))


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


def escribir_listas(base: Path, nombre: str, pistas, avisar_faltantes: bool = True):
    """
    Generador: escribe las dos .m3u8 de la lista con el orden de Tidal. Devuelve
    1 si falta alguna canción disponible (no se pudo descargar), si no 0.
    `pistas` son core.recursos.Pista.
    """
    locales = _archivos_por_isrc(base)
    laptop, plana, faltan = [], [], []
    for p in pistas:
        archivo = locales.get(p.isrc)
        if archivo is None:
            faltan.append(p)
            continue
        titulo = f"{p.artista} - {p.titulo}" if p.artista else p.titulo
        laptop.append((titulo, f"../{biblioteca.CANCIONES}/{archivo.name}", p.duracion or -1))
        plana.append((titulo, archivo.name, p.duracion or -1))

    nombre_m3u = _nombre_archivo(nombre) + ".m3u8"
    _escribir_m3u(base / "playlists" / nombre_m3u, laptop)
    _escribir_m3u(base / "playlists" / "plana" / nombre_m3u, plana)
    yield f"📝 Lista con {len(laptop)} canciones → {base / 'playlists' / nombre_m3u}"
    if not avisar_faltantes:
        return 0
    for p in faltan:
        yield f"   ⚠ {p.titulo} ({p.id}): {'sin archivo' if p.disponible else 'no disponible en Tidal'}"
    # Las no disponibles no cuentan como error: no hay forma de descargarlas
    return 1 if any(p.disponible for p in faltan) else 0
