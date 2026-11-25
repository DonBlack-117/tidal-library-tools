"""
Registro de los subprocesos vivos del servidor (scripts de consola y tiddl).

/shutdown cierra el servidor con os._exit, que no corre los finally de los
generadores: sin este registro, tiddl, ffmpeg o un script a medias quedaban
huérfanos escribiendo en la biblioteca.
"""

import os
import signal
import subprocess
import threading

_vivos: dict[subprocess.Popen, bool] = {}  # proceso → tiene grupo propio
_lock = threading.Lock()


def registrar(proc: subprocess.Popen, grupo: bool = False) -> None:
    """grupo=True si se lanzó con start_new_session: se termina con sus hijos."""
    with _lock:
        _vivos[proc] = grupo


def quitar(proc: subprocess.Popen) -> None:
    with _lock:
        _vivos.pop(proc, None)


def _senal(proc: subprocess.Popen, grupo: bool, sig: int) -> None:
    try:
        if grupo:
            os.killpg(proc.pid, sig)
        else:
            proc.send_signal(sig)
    except ProcessLookupError:
        pass


def terminar_todos(espera: float = 5.0) -> None:
    """SIGTERM a todos; los que sigan vivos tras `espera` segundos, SIGKILL."""
    with _lock:
        vivos = list(_vivos.items())
    for proc, grupo in vivos:
        if proc.poll() is None:
            _senal(proc, grupo, signal.SIGTERM)
    for proc, grupo in vivos:
        try:
            proc.wait(timeout=espera)
        except subprocess.TimeoutExpired:
            _senal(proc, grupo, signal.SIGKILL)
            proc.wait()
    with _lock:
        for proc, _ in vivos:
            _vivos.pop(proc, None)
