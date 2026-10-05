"""
Servidor Flask real con una sesión de Tidal falsa: las pruebas recorren la
página completa sin tocar la cuenta, tiddl ni adb.
"""

import threading

import pytest
from werkzeug.serving import make_server

import app as servidor
from core import recursos
from tests.conftest import FakeSession


def falsa_descarga(ids, base):
    for i in ids:
        yield f"Downloaded pista {i}"
    yield f"📂 {len(ids)} canción(es) nuevas en {base}/canciones"
    return 0


@pytest.fixture(scope="module")
def app_url():
    # No se llama base_url: pytest-base-url ya define uno de sesión.
    # Alcance de módulo: los parches se deshacen antes de las demás pruebas.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("core.sesion.sesion", lambda: FakeSession())
        mp.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: {"AAA111"})
        mp.setattr(recursos.motor, "descargar_pistas", falsa_descarga)
        mp.setattr("core.descargar.verificar_tiddl", lambda: (True, "ok"))
        mp.setattr(servidor, "_hay", lambda programa: False)  # sin adb ni zenity
        srv = make_server("127.0.0.1", 0, servidor.app, threaded=True)
        hilo = threading.Thread(target=srv.serve_forever, daemon=True)
        hilo.start()
        yield f"http://localhost:{srv.server_port}"
        srv.shutdown()


@pytest.fixture(autouse=True)
def cache_limpia():
    servidor._cache_recursos.clear()
