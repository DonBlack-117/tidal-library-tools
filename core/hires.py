"""
Mejora a Hi-Res (24-bit, hasta 192 kHz) las canciones de <base>/canciones.

Tidal solo entrega Hi-Res a sesiones PKCE: con la sesión de tiddl, una pista
marcada HIRES_LOSSLESS llega en 16-bit/44.1 kHz. Aquí se usa tidalapi con
login PKCE (su método documentado, el mismo que usa High Tide), se baja el
stream DASH (FLAC dentro de MP4), se extrae el FLAC con ffmpeg, se le copian
las etiquetas, la carátula y las letras del archivo actual, y solo se
reemplaza si la verificación sale bien. No se descifra nada: un stream
cifrado se salta.

Uso:
  python -m core.hires login     # una sola vez: inicia la sesión PKCE
  python -m core.hires [carpeta] # mejora todo lo pendiente (~/Music/Tidal)
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

import requests

from core.sesion import SESSION_FILE, sesion  # noqa: F401  (sesion se usa desde app.py y playlists)

BASE_DIR = Path(__file__).resolve().parent.parent
ESTADO = ".hires.json"  # ISRC → "hires" | "no-hires" | "cifrado"
CANCIONES = "canciones"

PAUSA = 1.0  # segundos entre pistas, para no provocar 429
ESPERA_429 = 60
MAX_REINTENTOS = 3


def login() -> int:
    """Login PKCE interactivo: abre el navegador y pide la URL de la página 'Oops'."""
    import tidalapi

    s = tidalapi.Session()
    url = s.pkce_login_url()
    print("Se abrirá el navegador. Inicia sesión en Tidal; al terminar verás una")
    print("página 'Oops'. Copia la URL completa de esa página y pégala aquí.\n")
    print(url, "\n")
    # xdg-open sin salida: el navegador imprime "Opening in existing browser
    # session." y se mezcla con la línea donde se pega la URL
    try:
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    redirect = input("URL de la página 'Oops': ").strip()
    s.process_auth_token(s.pkce_get_auth_token(redirect), is_pkce_token=True)
    if not s.check_login():
        print("❌ No se pudo iniciar sesión")
        return 1
    s.save_session_to_file(SESSION_FILE)
    print(f"✅ Sesión Hi-Res guardada en {SESSION_FILE.name}")
    return 0


def _cargar(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar(path: Path, datos: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(datos, indent=0, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _con_reintentos(fn):
    """Llama a fn(); si Tidal responde 429, espera y reintenta."""
    for intento in range(MAX_REINTENTOS + 1):
        try:
            return fn()
        except requests.HTTPError as e:
            codigo = getattr(e.response, "status_code", None)
            if codigo == 429 and intento < MAX_REINTENTOS:
                time.sleep(ESPERA_429)
                continue
            raise
        except Exception as e:
            if "429" in str(e) and intento < MAX_REINTENTOS:
                time.sleep(ESPERA_429)
                continue
            raise


def _bajar_segmentos(urls: list[str], destino: Path) -> None:
    with requests.Session() as http, open(destino, "wb") as f:
        for url in urls:
            for intento in range(MAX_REINTENTOS + 1):
                try:
                    r = http.get(url, timeout=60)
                    r.raise_for_status()
                    f.write(r.content)
                    break
                except requests.RequestException:
                    if intento == MAX_REINTENTOS:
                        raise
                    time.sleep(5)


def _copiar_metadatos(origen: Path, destino: Path) -> None:
    """Copia todas las etiquetas Vorbis y las imágenes del FLAC viejo al nuevo."""
    from mutagen.flac import FLAC

    viejo, nuevo = FLAC(origen), FLAC(destino)
    nuevo.delete()
    nuevo.clear_pictures()
    for clave, valores in (viejo.tags or {}).items():
        if clave.lower() != "encoder":
            nuevo[clave] = valores
    for pic in viejo.pictures:
        nuevo.add_picture(pic)
    nuevo.save()


def _verificar(path: Path, isrc: str) -> tuple[bool, str]:
    from mutagen.flac import FLAC

    try:
        f = FLAC(path)
    except Exception as e:
        return False, f"no es FLAC válido: {e}"
    if f.info.bits_per_sample <= 16 and f.info.sample_rate <= 44100:
        return False, "sigue en 16-bit/44.1 kHz"
    if not f.pictures:
        return False, "sin carátula"
    if isrc and (f.get("isrc") or [""])[0].upper() != isrc:
        return False, "ISRC distinto"
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if r.returncode != 0 or r.stderr.strip():
        return False, f"ffmpeg: {r.stderr.strip()[:120]}"
    return True, f"{f.info.bits_per_sample}-bit/{f.info.sample_rate / 1000:g} kHz"


def _mejorar_pista(s, track_id: str, actual: Path, isrc: str) -> tuple[str, str]:
    """Devuelve (estado, detalle). Estado: hires | no-hires | cifrado | error."""
    track = _con_reintentos(lambda: s.track(track_id))
    if "HIRES_LOSSLESS" not in (track.media_metadata_tags or []):
        return "no-hires", "Tidal no la tiene en Hi-Res"

    stream = _con_reintentos(track.get_stream)
    if stream.bit_depth <= 16 and stream.sample_rate <= 44100:
        return "no-hires", f"Tidal entrega {stream.bit_depth}-bit/{stream.sample_rate}"
    manifest = stream.get_stream_manifest()
    if (manifest.encryption_type or "NONE") != "NONE":
        return "cifrado", "stream cifrado, se omite"

    with tempfile.TemporaryDirectory(dir=actual.parent.parent) as tmp:
        tmp = Path(tmp)
        crudo, flac = tmp / "stream.mp4", tmp / "nuevo.flac"
        _bajar_segmentos(manifest.get_urls(), crudo)
        r = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(crudo),
                "-map",
                "0:a:0",
                "-c:a",
                "copy",
                str(flac),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if r.returncode != 0:
            return "error", f"ffmpeg: {r.stderr.strip()[:120]}"
        _copiar_metadatos(actual, flac)
        ok, detalle = _verificar(flac, isrc)
        if not ok:
            return "error", detalle
        shutil.move(str(flac), actual.with_name(actual.name + ".hires-tmp"))
        actual.with_name(actual.name + ".hires-tmp").replace(actual)
        return "hires", detalle


def mejorar(base: Path):
    """
    Generador (para SSE): mejora a Hi-Res los FLAC de 16-bit de
    <base>/canciones que Tidal ofrece en Hi-Res. Devuelve el código de salida.
    """
    from mutagen.flac import FLAC

    base = Path(base).expanduser()
    s = sesion()
    if s is None:
        yield "⚠ Hi-Res: falta la sesión PKCE. Ejecuta una vez:"
        yield f"    cd {BASE_DIR} && .venv/bin/python -m core.hires login"
        return 0

    registro = _cargar(base / ".tidal_ids.json")  # ID → ISRC
    ids_por_isrc: dict[str, list[str]] = {}
    for tid, isrc in registro.items():
        if isrc:
            ids_por_isrc.setdefault(isrc, []).append(tid)

    estado = _cargar(base / ESTADO)
    candidatas = []
    for p in sorted((base / CANCIONES).glob("*.flac")):
        try:
            f = FLAC(p)
        except Exception:
            continue
        isrc = (f.get("isrc") or [""])[0].upper()
        if f.info.bits_per_sample > 16 or f.info.sample_rate > 44100:
            continue
        if not isrc or estado.get(isrc) in ("no-hires", "cifrado", "hires"):
            continue
        if isrc in ids_por_isrc:
            candidatas.append((p, isrc))

    if not candidatas:
        yield "✅ Hi-Res: no hay canciones pendientes de mejorar"
        return 0

    yield f"🎚 Hi-Res: revisando {len(candidatas)} canción(es) en 16-bit"
    mejoradas = errores = 0
    for n, (p, isrc) in enumerate(candidatas, 1):
        resultado, detalle = "error", ""
        for tid in ids_por_isrc[isrc]:
            try:
                resultado, detalle = _mejorar_pista(s, tid, p, isrc)
            except Exception as e:
                resultado, detalle = "error", str(e)[:150]
            if resultado != "error":
                break
        if resultado == "error":
            errores += 1
            yield f"   ❌ {p.stem}: {detalle}"
        else:
            estado[isrc] = resultado
            _guardar(base / ESTADO, estado)
            if resultado == "hires":
                mejoradas += 1
                yield f"   ⬆ {p.stem}: {detalle}"
        yield f"   {n}/{len(candidatas)}"   # la web lo usa como barra de progreso
        time.sleep(PAUSA)

    yield f"🎚 Hi-Res: {mejoradas} mejorada(s), {errores} con error"
    return 1 if errores else 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["login"]:
        sys.exit(login())
    carpeta = Path(
        sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Music" / "Tidal"
    )
    gen = mejorar(carpeta)
    try:
        while True:
            print(next(gen), flush=True)
    except StopIteration as fin:
        sys.exit(fin.value or 0)
