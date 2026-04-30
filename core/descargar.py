import re
import shutil
import subprocess
import os

# tiddl 3.2.x usa: tiddl download url <URL_o_shorthand>
# El flag de directorio base es --path (no --output)
# Acepta URL completa o shorthand: album/123, track/456, etc.

# Calidad automática por tipo de recurso:
#   playlist/artista → normal (contenido mixto; no se puede garantizar lossless)
#   album            → high   (los álbumes suelen tener formato uniforme)
#   track            → max    (pista individual; intentar mejor calidad disponible)
_AUTO_QUALITY: dict[str, str] = {
    "playlist": "normal",
    "artist":   "normal",
    "album":    "high",
    "track":    "max",
}


def _parse_url_type(url: str) -> str:
    """Extrae el tipo de recurso Tidal de una URL o shorthand."""
    url_lower = url.lower()
    for rtype in ("playlist", "artist", "album", "track"):
        if f"/{rtype}/" in url_lower or url_lower.startswith(f"{rtype}/"):
            return rtype
    return "unknown"


def _tiddl_exe() -> str:
    """Devuelve la ruta al ejecutable tiddl o lanza FileNotFoundError."""
    exe = shutil.which("tiddl")
    if not exe:
        raise FileNotFoundError("tiddl no encontrado en PATH. Instala con: pip install tiddl")
    return exe


def _configurar_caratula(enabled: bool) -> None:
    """Activa o desactiva la descarga de carátulas en el config de tiddl."""
    value = "true" if enabled else "false"
    exe = shutil.which("tiddl")
    if not exe:
        return
    for key in ("metadata.cover", "cover.save"):
        subprocess.run(
            [exe, "config", "set", key, value],
            capture_output=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )


def descargar_recurso(url: str, output_dir: str = "", quality: str = "AUTO", cover: bool = True):
    """
    Descarga un recurso de Tidal via tiddl como subproceso.
    Hace yield de cada línea de salida para streaming SSE.
    """
    q = quality.lower()
    if q == "auto":
        rtype = _parse_url_type(url)
        tiddl_quality = _AUTO_QUALITY.get(rtype, "normal")
        type_label = {"playlist": "playlist", "artist": "artista", "album": "álbum",
                      "track": "pista", "unknown": "recurso"}.get(rtype, rtype)
        yield f"🔍 Tipo detectado: {type_label} → calidad: {tiddl_quality.upper()}"
    elif q in {"max", "high", "normal", "low"}:
        tiddl_quality = q
    else:
        tiddl_quality = "normal"

    try:
        exe = _tiddl_exe()
    except FileNotFoundError as e:
        yield f"❌ {e}"
        return 1

    _configurar_caratula(cover)

    cmd = [
        exe,
        "download",
        "--track-quality", tiddl_quality,
        "--skip-errors",
    ]

    if output_dir:
        cmd += ["--path", output_dir]

    # El subcomando "url" acepta la URL/shorthand al final
    cmd += ["url", url]

    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",   # evita UnicodeEncodeError con caracteres Rich en Windows
    }

    yield f"▶ Recurso: {url}  (calidad: {tiddl_quality.upper()})"
    if output_dir:
        yield f"📁 Destino: {output_dir}"
    yield ""

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",           # reemplaza caracteres no decodificables en vez de fallar
            bufsize=1,
            env=env,
        )
    except FileNotFoundError:
        yield "❌ tiddl no encontrado en PATH. Instala con:  pip install tiddl"
        return 1
    except Exception as e:
        yield f"❌ Error al iniciar tiddl: {e}"
        return 1

    for line in iter(process.stdout.readline, ""):
        yield line.rstrip()

    process.stdout.close()
    process.wait()
    return process.returncode


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
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        ok   = result.returncode == 0
        msgs = (result.stdout + result.stderr).strip().splitlines()
        msg  = msgs[0] if msgs else ("Autenticado" if ok else "No autenticado")
        return ok, msg
    except subprocess.TimeoutExpired:
        return False, "Tiempo de espera agotado al verificar tiddl"
    except FileNotFoundError as e:
        return False, str(e)
