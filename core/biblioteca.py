"""
Biblioteca plana: todo el audio en <base>/canciones y los .lrc en <base>/lyrics,
sin subcarpetas ni número de pista en el nombre.

tiddl descarga primero en <base>/.descarga con su plantilla de carpetas; al
terminar, `aplanar` mueve cada archivo a su sitio. Como tiddl ya no puede ver
lo descargado (los nombres cambian), las pistas ya presentes se reconocen por
ISRC: `pendientes_my_tracks` pide a Tidal el ISRC de cada favorito (guardado en
<base>/.tidal_ids.json para no repetirlo) y solo devuelve los que faltan.
"""

import json
import re
import shutil
import time
import unicodedata
from pathlib import Path

CANCIONES = "canciones"
LYRICS = "lyrics"
STAGING = ".descarga"
REGISTRO = ".tidal_ids.json"
AUDIO_EXT = (".flac", ".m4a")
ATMOS_SUFFIX = " [Dolby Atmos]"

ESPERA_429 = 60
MAX_REINTENTOS_429 = 3


def _tags(path: Path) -> dict:
    """ISRC, artista y álbum de un archivo de audio (FLAC o M4A)."""
    import mutagen

    try:
        m = mutagen.File(path)
    except Exception:
        return {}
    if m is None or m.tags is None:
        return {}
    t = m.tags
    if path.suffix == ".m4a":
        isrc = t.get("----:com.apple.iTunes:ISRC")
        return {
            "isrc": bytes(isrc[0]).decode(errors="ignore") if isrc else "",
            "artist": str((t.get("\xa9ART") or [""])[0]),
            "album": str((t.get("\xa9alb") or [""])[0]),
        }
    return {
        "isrc": (t.get("isrc") or [""])[0],
        "artist": (t.get("artist") or [""])[0],
        "album": (t.get("album") or [""])[0],
    }


def isrcs_locales(base: Path) -> set[tuple[str, str]]:
    """Pares (ISRC, extensión) de las canciones ya presentes en <base>/canciones."""
    carpeta = base / CANCIONES
    if not carpeta.is_dir():
        return set()
    pares = set()
    for p in carpeta.iterdir():
        if p.suffix in AUDIO_EXT:
            isrc = _tags(p).get("isrc")
            if isrc:
                pares.add((isrc.upper(), p.suffix))
    return pares


def _flac_hires(path: Path) -> bool:
    """
    True si el FLAC es de más de 16 bits o más de 44.1 kHz. Lee solo los 42
    primeros bytes (STREAMINFO), sin cargar carátula ni letras: rápido para
    recorrer toda la biblioteca.
    """
    try:
        with open(path, "rb") as f:
            b = f.read(42)
    except OSError:
        return False
    if len(b) < 42 or b[:4] != b"fLaC":
        return False
    d = b[8:]                                   # datos de STREAMINFO
    rate = (d[10] << 12) | (d[11] << 4) | (d[12] >> 4)
    bits = (((d[12] & 0x01) << 4) | (d[13] >> 4)) + 1
    return bits > 16 or rate > 44100


def estadisticas(base: Path) -> dict:
    """Números de la biblioteca para la franja de estado de la web."""
    carpeta = base / CANCIONES
    audio = [p for p in carpeta.iterdir() if p.suffix in AUDIO_EXT] if carpeta.is_dir() else []
    tam = sum(p.stat().st_size for p in audio)
    letras = base / LYRICS
    listas = base / "playlists"
    return {
        "canciones": len(audio),
        "hires": sum(1 for p in audio if p.suffix == ".flac" and _flac_hires(p)),
        "letras": len(list(letras.glob("*.lrc"))) if letras.is_dir() else 0,
        "playlists": sorted(p.stem for p in listas.glob("*.m3u8")) if listas.is_dir() else [],
        "gb": round(tam / 1024 ** 3, 1),
    }


def _seguro(texto: str) -> str:
    """
    Quita los caracteres que Android (almacenamiento compartido) no admite en
    nombres y normaliza a NFC ("ñ" como un solo carácter, no "n" + tilde), para
    que los nombres se comparen igual en la laptop y en el teléfono.
    """
    texto = unicodedata.normalize("NFC", texto)
    return re.sub(r'[:*?<>|\\]', "-", texto.replace('"', "'"))


def _limpio(texto: str) -> str:
    return _seguro(texto.replace("/", "-")).strip()


def _nombre_base(path: Path) -> str:
    nombre = _seguro(re.sub(r"^\d+ - ", "", path.stem))
    if "Dolby Atmos" in path.parent.name and "Atmos" not in nombre:
        nombre += ATMOS_SUFFIX
    return nombre


def _nombre_libre(carpeta: Path, nombre: str, ext: str, tags: dict) -> str:
    """Primer nombre que no choque con uno existente: título, + artista, + álbum, + número."""
    candidatos = [nombre]
    if tags.get("artist"):
        candidatos.append(f"{nombre} - {_limpio(tags['artist'])}")
        if tags.get("album"):
            candidatos.append(f"{nombre} - {_limpio(tags['artist'])} ({_limpio(tags['album'])})")
    for c in candidatos:
        if not (carpeta / (c + ext)).exists():
            return c
    n = 2
    while (carpeta / f"{candidatos[-1]} ({n}){ext}").exists():
        n += 1
    return f"{candidatos[-1]} ({n})"


def aplanar(base: Path):
    """
    Mueve el audio de <base>/.descarga a <base>/canciones y sus .lrc a
    <base>/lyrics. Si ya hay una canción con el mismo ISRC y formato, la nueva
    se descarta. Al final borra <base>/.descarga.
    """
    staging = base / STAGING
    if not staging.is_dir():
        return
    canciones, lyrics = base / CANCIONES, base / LYRICS
    canciones.mkdir(parents=True, exist_ok=True)
    lyrics.mkdir(parents=True, exist_ok=True)

    presentes = isrcs_locales(base)
    movidas = repetidas = 0

    for audio in sorted(p for p in staging.rglob("*") if p.suffix in AUDIO_EXT):
        tags = _tags(audio)
        clave = (tags.get("isrc", "").upper(), audio.suffix)
        if clave[0] and clave in presentes:
            repetidas += 1
            continue
        nombre = _nombre_libre(canciones, _nombre_base(audio), audio.suffix, tags)
        shutil.move(str(audio), canciones / (nombre + audio.suffix))
        lrc = audio.with_suffix(".lrc")
        if lrc.exists():
            shutil.move(str(lrc), lyrics / (nombre + ".lrc"))
        if clave[0]:
            presentes.add(clave)
        movidas += 1

    shutil.rmtree(staging, ignore_errors=True)
    if movidas:
        yield f"📂 {movidas} canción(es) nuevas en {canciones}"
    if repetidas:
        yield f"↩ {repetidas} descartada(s): ya estaban en {CANCIONES}/ (mismo ISRC)"


def _cargar_registro(base: Path) -> dict[str, str | None]:
    try:
        return json.loads((base / REGISTRO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_registro(base: Path, registro: dict) -> None:
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / (REGISTRO + ".tmp")
    tmp.write_text(json.dumps(registro, indent=0, sort_keys=True), encoding="utf-8")
    tmp.replace(base / REGISTRO)


def pendientes_my_tracks(base: Path):
    """
    Devuelve (con `yield from`) los IDs de My Tracks cuyo ISRC no está en
    <base>/canciones. Los favoritos que Tidal ya no tiene (404) se registran
    como None y no se vuelven a intentar.
    """
    from rich.console import Console
    from tiddl.cli.ctx import ContextObject
    from tiddl.core.api.exceptions import ApiError

    api = ContextObject(False, None, Console(quiet=True)).api
    favoritos = [str(i) for i in api.get_favorites().model_dump()["TRACK"]]
    registro = _cargar_registro(base)
    nuevos = [i for i in favoritos if i not in registro]

    if nuevos:
        yield f"🔎 Consultando {len(nuevos)} favorito(s) nuevos en Tidal (ISRC)…"
    for n, tid in enumerate(nuevos, 1):
        for intento in range(MAX_REINTENTOS_429 + 1):
            try:
                registro[tid] = (api.get_track(tid).isrc or "").upper() or None
                break
            except ApiError as e:
                if e.status == 429 and intento < MAX_REINTENTOS_429:
                    yield f"⏳ Límite de Tidal (429); espero {ESPERA_429}s"
                    time.sleep(ESPERA_429)
                    continue
                if e.status == 404:
                    registro[tid] = None
                break
            except Exception:
                break
        if n % 100 == 0:
            _guardar_registro(base, registro)
        if n % 10 == 0 or n == len(nuevos):
            yield f"   {n}/{len(nuevos)}"   # la web lo usa como barra de progreso
    _guardar_registro(base, registro)

    locales = {isrc for isrc, _ in isrcs_locales(base)}
    pendientes = [i for i in favoritos
                  if i not in registro or (registro[i] and registro[i] not in locales)]
    no_disponibles = sum(1 for i in favoritos if i in registro and registro[i] is None)

    yield (f"📋 My Tracks: {len(favoritos)} favoritos, {len(favoritos) - len(pendientes) - no_disponibles} "
           f"ya descargados, {no_disponibles} no disponibles en Tidal, {len(pendientes)} por descargar")
    return pendientes
