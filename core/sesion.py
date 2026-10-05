"""
Sesión de Tidal compartida por todas las herramientas.

Es la sesión PKCE (la misma que necesita Hi-Res), guardada en
tidal-pkce.session.json. Se crea una vez con:

    .venv/bin/python -m core.hires login

tiddl tiene su propia sesión y solo se usa para descargar.
"""

import sys
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_FILE = BASE_DIR / "tidal-pkce.session.json"  # ignorado por *.session.json
COMANDO_LOGIN = ".venv/bin/python -m core.hires login"


class SinSesion(RuntimeError):
    """No hay sesión PKCE guardada o caducó."""

    def __init__(self) -> None:
        super().__init__(f"Falta la sesión de Tidal. Ejecuta una vez: {COMANDO_LOGIN}")


# El servidor web atiende varias peticiones a la vez y todas leen y renuevan el
# mismo archivo: sin candado, dos escrituras a la vez pueden dejarlo cortado
_lock = threading.Lock()


def sesion():
    """
    Sesión PKCE guardada, o None si no existe o caducó. Si falla por otra
    causa (red, Tidal caído), el error se escribe en stderr para no confundirlo
    con "falta iniciar sesión".
    """
    import tidalapi

    with _lock:
        if not SESSION_FILE.exists():
            return None
        s = tidalapi.Session()
        try:
            if not (s.load_session_from_file(SESSION_FILE) and s.check_login()):
                return None
        except Exception as e:  # noqa: BLE001  tidalapi lanza tipos variados (requests, KeyError, JSON)
            print(f"⚠ No se pudo comprobar la sesión de Tidal: {e!r}", file=sys.stderr)
            return None
        s.audio_quality = tidalapi.Quality.hi_res_lossless
        _guardar(s)  # el token pudo renovarse
        return s


def _guardar(s) -> None:
    """Escribe en un temporal y lo reemplaza: el archivo nunca queda a medias."""
    tmp = SESSION_FILE.with_name(SESSION_FILE.name + ".tmp")
    s.save_session_to_file(tmp)
    tmp.replace(SESSION_FILE)


def requerida():
    """Sesión PKCE o SinSesion con el comando para crearla."""
    s = sesion()
    if s is None:
        raise SinSesion()
    return s


def para_scripts():
    """
    Sesión para los scripts de consola (sincronizar, mejorar calidad, duplicados).
    Imprime cómo iniciar sesión y devuelve None si no hay.
    """
    s = sesion()
    if s is None:
        print(f"❌ {SinSesion()}")
        return None
    print("✅ Sesión iniciada correctamente")
    return s
