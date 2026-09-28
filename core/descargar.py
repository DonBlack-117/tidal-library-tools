import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from core import biblioteca, hires

# tiddl 3.4.x:  tiddl download [OPCIONES] url <URL_o_shorthand>
#               tiddl download [OPCIONES] fav -t track
# La configuración (metadatos, letras, carátula, plantilla) vive en
# ~/.tiddl/config.toml; tiddl 3.4 no tiene subcomando `config`.
# La calidad siempre es `max`: tiddl pide HI_RES_LOSSLESS y Tidal entrega
# lo mejor disponible para cada pista (Hi-Res, Lossless o AAC).
#
# Dolby Atmos: con la petición de tiddl, Tidal entrega SOLO el stream Atmos de
# las pistas que tienen ambas mezclas. Por eso hay una segunda pasada con
# core/tiddl_estereo.py (añade `immersiveaudio=false`) y `-da none`, que baja
# la versión estéreo (.flac) y salta lo que ya existe.
# No se descifra nada: un Atmos cifrado o ilegible se borra y se anota en
# logs/tidal_atmos_omitidas.txt.
#
# Biblioteca plana (core/biblioteca.py): tiddl descarga en <destino>/.descarga
# y al final todo se mueve a <destino>/canciones y <destino>/lyrics, sin
# subcarpetas ni número de pista. Lo ya descargado se reconoce por ISRC.
#
# Hi-Res (core/hires.py): Tidal solo entrega 24-bit a sesiones PKCE, y tiddl
# no usa PKCE. Al final de cada descarga, los FLAC de 16-bit que Tidal tiene
# en Hi-Res se vuelven a bajar con tidalapi (PKCE) y se reemplazan.

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
ATMOS_LOG = LOGS_DIR / "tidal_atmos_omitidas.txt"
ERRORES_LOG = LOGS_DIR / "tidal_descarga_errores.txt"

DEFAULT_OUTPUT_DIR = str(Path.home() / "Music" / "Tidal")
ATMOS_SUFFIX = " [Dolby Atmos]"

# Reintentos cuando Tidal responde 429 (demasiadas peticiones)
MAX_REINTENTOS_429 = 3
ESPERA_429 = 60
# Segundos sin actividad antes de considerar que tiddl se ha colgado
INACTIVIDAD_MAX = 300

# Códecs que Tidal usa para Dolby Atmos
_ATMOS_CODECS = {"eac3", "ac3", "ac4"}
_ERROR_PREFIXES = ("Error", "API Error", "Can't stream")


def _tiddl_exe() -> str:
    """Devuelve la ruta al tiddl del .venv (junto a sys.executable) o del PATH."""
    venv_exe = Path(sys.executable).parent / "tiddl"
    if venv_exe.exists():
        return str(venv_exe)
    exe = shutil.which("tiddl")
    if not exe:
        raise FileNotFoundError("tiddl no encontrado. Instala con: .venv/bin/pip install tiddl")
    return exe


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",  # evita UnicodeEncodeError con caracteres Rich
        "COLUMNS": "250",             # evita que Rich parta las rutas en varias líneas
    }


def _ultima_actividad(vigilar_dir: Path | None) -> float:
    """Momento de la última actividad de tiddl: su log de depuración o un temporal que crece."""
    marcas = [0.0]
    tiddl_home = Path(os.environ.get("TIDDL_PATH") or Path.home() / ".tiddl")
    try:
        marcas.append((tiddl_home / "latest.log").stat().st_mtime)
    except OSError:
        pass
    if vigilar_dir and vigilar_dir.is_dir():
        for p in vigilar_dir.rglob("tmp*"):
            try:
                marcas.append(p.stat().st_mtime)
            except OSError:
                pass
    return max(marcas)


def _vigilar(process: subprocess.Popen, vigilar_dir: Path | None, estado: dict) -> None:
    """
    tiddl descarga con aiohttp sin timeout: si una conexión se cuelga, el
    proceso se queda parado para siempre. Si no hay actividad en
    INACTIVIDAD_MAX segundos, se termina para poder reintentar.
    """
    while process.poll() is None:
        time.sleep(15)
        inactivo = time.time() - max(_ultima_actividad(vigilar_dir), estado["ultima_linea"])
        if inactivo > INACTIVIDAD_MAX and process.poll() is None:
            estado["estancado"] = True
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            return


def _ejecutar(cmd: list[str], errores: list[str], silenciar_existentes: bool = False,
              vigilar_dir: Path | None = None):
    """
    Ejecuta tiddl haciendo yield de cada línea. Devuelve el código de salida.
    Las líneas de error se añaden a `errores`; si tiddl se cuelga, se termina
    y se añade una línea "Estancado".
    """
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(BASE_DIR),
            env=_env(),
        )
    except Exception as e:
        yield f"❌ Error al iniciar tiddl: {e}"
        return 1

    estado = {"ultima_linea": time.time(), "estancado": False}
    threading.Thread(target=_vigilar, args=(process, vigilar_dir, estado), daemon=True).start()

    try:
        for line in iter(process.stdout.readline, ""):
            estado["ultima_linea"] = time.time()
            line = line.rstrip()
            if line.startswith(_ERROR_PREFIXES):
                errores.append(line)
            if silenciar_existentes and line.startswith(("Exists ", "Skipping ", "Auth token")):
                continue
            yield line
    finally:
        # Si el cliente corta el SSE (botón Detener), no dejar tiddl huérfano
        if process.poll() is None and sys.exc_info()[0] is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        process.stdout.close()

    process.wait()
    if estado["estancado"]:
        msg = f"Estancado: tiddl sin actividad {INACTIVIDAD_MAX // 60} min, detenido"
        errores.append(msg)
        yield f"⚠ {msg}"
    return process.returncode


# ── Favoritos (para IDs, ISRC y detección de Atmos) ──────────────────────────

class _Favoritos:
    """Índice perezoso de las pistas favoritas, usando la API (y la caché) de tiddl."""

    def __init__(self) -> None:
        self._por_titulo_album: dict[tuple[str, str], object] | None = None
        self._por_titulo: dict[str, list] = {}

    def _cargar(self) -> None:
        self._por_titulo_album = {}
        try:
            from rich.console import Console
            from tiddl.cli.ctx import ContextObject

            api = ContextObject(False, None, Console(quiet=True)).api
            for tid in api.get_favorites().model_dump()["TRACK"]:
                try:
                    t = api.get_track(tid)
                except Exception:
                    continue
                titulo = f"{t.title} ({t.version})" if t.version else t.title
                self._por_titulo_album[(titulo.casefold(), t.album.title.casefold())] = t
                self._por_titulo.setdefault(t.title.casefold(), []).append(t)
                self._por_titulo.setdefault(titulo.casefold(), []).append(t)
        except Exception:
            pass

    def buscar(self, titulo: str, album: str):
        if self._por_titulo_album is None:
            self._cargar()
        return self._por_titulo_album.get((titulo.casefold(), album.casefold()))

    def buscar_titulo(self, titulo: str) -> list:
        if self._por_titulo_album is None:
            self._cargar()
        return self._por_titulo.get(titulo.casefold(), [])


def _anotar_atmos(track_id, titulo: str, album: str, motivo: str) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    with open(ATMOS_LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{track_id}\t{titulo}\t{album}\t{motivo}\n")


# ── Post-proceso ──────────────────────────────────────────────────────────────

def _ffprobe_audio(path: Path) -> dict:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name,codec_tag_string",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        streams = json.loads(out.stdout or "{}").get("streams", [])
        return streams[0] if streams else {}
    except Exception:
        return {}


def _decoder_disponible(codec: str) -> bool:
    if not codec or not shutil.which("ffmpeg"):
        return False
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-decoders"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return False
    return any(len(p) > 1 and p[1] == codec for p in (l.split() for l in out.splitlines()))


def _esta_cifrado(path: Path, info: dict) -> bool:
    """Detecta cifrado CENC (cajas tenc/sinf/enca) o un stream que no se puede decodificar."""
    if info.get("codec_tag_string") == "enca":
        return True
    try:
        # Las cajas de cifrado van en el moov/init segment, al principio del archivo
        with open(path, "rb") as f:
            cabecera = f.read(1024 * 1024)
        if b"tenc" in cabecera or b"sinf" in cabecera or b"enca" in cabecera:
            return True
    except OSError:
        return True
    if _decoder_disponible(info.get("codec_name", "")):
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-t", "10", "-i", str(path), "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode != 0 or bool(r.stderr.strip())
    return False


def _postprocesar(output_dir: str, errores: list[str]):
    """
    - Atmos cifrado o ilegible → se borra y se anota en logs/tidal_atmos_omitidas.txt
    - Pistas Atmos con error en tiddl → se anotan en el mismo log
    - Atmos con versión estéreo al lado → se renombra con " [Dolby Atmos]"
    - M4A sin ISRC → se añade (tiddl solo lo escribe en FLAC)
    - Errores de tiddl → logs/tidal_descarga_errores.txt
    """
    from mutagen.mp4 import MP4, MP4FreeForm

    favoritos = _Favoritos()
    base = Path(output_dir).expanduser()
    # Todos los .m4a (son pocos: Atmos y AAC), así se reparan también los de
    # una ejecución interrumpida antes del post-proceso
    nuevos = sorted(base.rglob("*.m4a")) if base.is_dir() else []

    omitidas = renombradas = isrc_fix = 0

    for path in nuevos:
        try:
            tags = MP4(path).tags or {}
        except Exception:
            tags = {}
        titulo = str((tags.get("\xa9nam") or [path.stem])[0])
        album = str((tags.get("\xa9alb") or [""])[0])

        info = _ffprobe_audio(path)
        es_atmos = info.get("codec_name") in _ATMOS_CODECS

        if es_atmos and _esta_cifrado(path, info):
            track = favoritos.buscar(titulo, album)
            track_id = getattr(track, "id", "desconocido")
            path.unlink(missing_ok=True)
            if not path.with_suffix(".flac").exists():
                path.with_suffix(".lrc").unlink(missing_ok=True)
            _anotar_atmos(track_id, titulo, album, "cifrado/ilegible")
            omitidas += 1
            yield f"⏭ Atmos omitida (cifrada): {titulo} [{track_id}]"
            continue

        if "----:com.apple.iTunes:ISRC" not in tags:
            track = favoritos.buscar(titulo, album)
            if track is not None and getattr(track, "isrc", None):
                try:
                    m = MP4(path)
                    m["----:com.apple.iTunes:ISRC"] = [MP4FreeForm(track.isrc.encode())]
                    m.save()
                    isrc_fix += 1
                except Exception:
                    pass

        if es_atmos and path.with_suffix(".flac").exists() and not path.stem.endswith(ATMOS_SUFFIX):
            destino = path.with_name(path.stem + ATMOS_SUFFIX + ".m4a")
            path.rename(destino)
            lrc = path.with_suffix(".lrc")
            if lrc.exists():
                shutil.copy2(lrc, destino.with_suffix(".lrc"))
            renombradas += 1

    # Errores de tiddl; los de pistas Atmos van también al log de Atmos
    if errores:
        LOGS_DIR.mkdir(exist_ok=True)
        with open(ERRORES_LOG, "a", encoding="utf-8") as f:
            f.write(f"# {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            f.writelines(e + "\n" for e in errores)
        for linea in errores:
            if not linea.startswith("Error "):
                continue
            titulo = linea[len("Error "):].rsplit(" - ", 1)[0].strip()
            for t in favoritos.buscar_titulo(titulo):
                if "DOLBY_ATMOS" in (t.audioModes or []):
                    _anotar_atmos(t.id, t.title, t.album.title, f"error tiddl: {linea}")
                    omitidas += 1
        yield f"⚠ {len(errores)} error(es) de tiddl → {ERRORES_LOG.relative_to(BASE_DIR)}"

    if omitidas:
        yield f"⚠ {omitidas} pista(s) Atmos omitidas → {ATMOS_LOG.relative_to(BASE_DIR)}"
    if renombradas:
        yield f"🎧 {renombradas} versión(es) Dolby Atmos guardadas junto a su versión estéreo"
    if isrc_fix:
        yield f"🏷 ISRC añadido a {isrc_fix} archivo(s) M4A"


def _pasada_con_reintentos(cmd: list[str], nombre: str, vigilar_dir: Path,
                           silenciar_existentes: bool = False):
    """
    Ejecuta una pasada de tiddl. Si Tidal limita la tasa (429) o tiddl se
    cuelga, espera y repite: lo ya descargado se salta, así que solo se
    reintentan las pistas pendientes. Devuelve (código, errores del último intento).
    """
    for intento in range(1, MAX_REINTENTOS_429 + 2):
        errores: list[str] = []
        code = yield from _ejecutar(cmd, errores, silenciar_existentes, vigilar_dir)
        limitadas = sum("429/" in e for e in errores)
        estancado = any(e.startswith("Estancado") for e in errores)
        if not (limitadas or estancado) or intento > MAX_REINTENTOS_429:
            return code, errores
        motivo = (f"{limitadas} pista(s) rechazadas por límite de Tidal (429)"
                  if limitadas else "tiddl se colgó")
        yield ""
        yield f"⏳ {nombre}: {motivo}; reintento {intento}/{MAX_REINTENTOS_429} en {ESPERA_429}s"
        time.sleep(ESPERA_429)
        yield from _limpiar_temporales(str(vigilar_dir))
        silenciar_existentes = True


def _limpiar_temporales(output_dir: str):
    """Borra los temporales (tmpXXXXXXXX) que deja tiddl si se interrumpe una descarga."""
    base = Path(output_dir)
    if not base.is_dir():
        return
    borrados = 0
    for p in base.rglob("tmp*"):
        if p.is_file() and not p.suffix and re.fullmatch(r"tmp[a-z0-9_]{8}", p.name):
            p.unlink(missing_ok=True)
            borrados += 1
    if borrados:
        yield f"🧹 {borrados} temporal(es) de una descarga interrumpida eliminados"


def _descargar(destino_args: list[str], output_dir: str):
    try:
        exe = _tiddl_exe()
    except FileNotFoundError as e:
        yield f"❌ {e}"
        return 1

    base = Path(output_dir or DEFAULT_OUTPUT_DIR).expanduser()
    yield f"📁 Destino: {base / biblioteca.CANCIONES}  (letras en {biblioteca.LYRICS}/)"

    # tiddl trabaja en la carpeta temporal; al final se aplana
    output_dir = str(base / biblioteca.STAGING)
    # --scan-path: tiddl busca archivos existentes ahí, no en -p
    opciones = ["download", "-q", "max", "-p", output_dir, "--scan-path", output_dir]
    estereo = [sys.executable, "-m", "core.tiddl_estereo"]

    # Restos de una ejecución interrumpida: se aplanan antes de empezar
    yield from biblioteca.aplanar(base)
    yield ""

    code, errores = yield from _pasada_con_reintentos(
        [exe, *opciones, "-da", "allow", *destino_args], "Primera pasada", Path(output_dir))

    yield ""
    yield "▶ Segunda pasada: versión estéreo de las pistas que también tienen Dolby Atmos"
    code2, errores_estereo = yield from _pasada_con_reintentos(
        [*estereo, *opciones, "-da", "none", *destino_args], "Segunda pasada",
        Path(output_dir), silenciar_existentes=True)
    # Los errores que ya salieron en la primera pasada no se duplican
    errores += [e for e in errores_estereo if e not in errores]

    yield from _postprocesar(output_dir, errores)
    yield from _limpiar_temporales(output_dir)
    yield from biblioteca.aplanar(base)
    # tiddl solo recibe 16-bit; lo que Tidal tiene en Hi-Res se mejora aparte
    yield ""
    code3 = yield from hires.mejorar(base)
    return code or code2 or code3


def descargar_recurso(url: str, output_dir: str = ""):
    """
    Descarga una URL/shorthand de Tidal en calidad máxima.
    Hace yield de cada línea para SSE y devuelve el código de salida de tiddl.
    """
    # Las playlists van por core.playlists: salta lo ya descargado (ISRC) y crea el .m3u8
    if re.search(r"playlist/[0-9a-f]{8}-", url, re.I):
        from core.playlists import descargar_playlist
        return (yield from descargar_playlist(url, output_dir))
    yield f"▶ Recurso: {url}  (calidad: MAX)"
    return (yield from _descargar(["url", url], output_dir))


def descargar_mis_tracks(output_dir: str = ""):
    """
    Descarga todas las pistas favoritas (My Tracks) en calidad máxima.
    Hace yield de cada línea para SSE y devuelve el código de salida de tiddl.
    """
    yield "▶ My Tracks (favoritos de tipo track)  (calidad: MAX)"
    base = Path(output_dir or DEFAULT_OUTPUT_DIR).expanduser()
    try:
        pendientes = yield from biblioteca.pendientes_my_tracks(base)
    except Exception as e:
        yield f"❌ No se pudo leer My Tracks: {e}"
        return 1
    if not pendientes:
        yield "✅ Todo al día: no hay canciones nuevas"
        yield from biblioteca.aplanar(base)
        yield ""
        return (yield from hires.mejorar(base))
    return (yield from _descargar(["url", *(f"track/{i}" for i in pendientes)], output_dir))


def verificar_tiddl() -> tuple[bool, str]:
    """Comprueba si tiddl está instalado y tiene sesión activa."""
    try:
        result = subprocess.run(
            [_tiddl_exe(), "auth", "refresh"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            env=_env(),
        )
        ok   = result.returncode == 0
        msgs = (result.stdout + result.stderr).strip().splitlines()
        msg  = msgs[0] if msgs else ("Autenticado" if ok else "No autenticado")
        return ok, msg
    except subprocess.TimeoutExpired:
        return False, "Tiempo de espera agotado al verificar tiddl"
    except FileNotFoundError as e:
        return False, str(e)


if __name__ == "__main__":
    # Uso: python -m core.descargar [carpeta]   → descarga My Tracks
    gen = descargar_mis_tracks(sys.argv[1] if len(sys.argv) > 1 else "")
    try:
        while True:
            print(next(gen), flush=True)
    except StopIteration as stop:
        sys.exit(stop.value if isinstance(stop.value, int) else 0)
