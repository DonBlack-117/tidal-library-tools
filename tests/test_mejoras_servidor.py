"""Cierre sin huérfanos, sesión en memoria e índice de pistas por ID."""

import subprocess
import sys
import time
from types import SimpleNamespace

from core import descargar, procesos, sesion


# ── /shutdown: procesos.terminar_todos ───────────────────────────────────────


def test_terminar_todos_mata_procesos_registrados():
    solo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    grupo = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
    )
    procesos.registrar(solo)
    procesos.registrar(grupo, grupo=True)

    procesos.terminar_todos(espera=5)

    assert solo.poll() is not None
    assert grupo.poll() is not None
    assert procesos._vivos == {}


def test_terminar_todos_ignora_los_que_ya_terminaron():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    procesos.registrar(p)
    procesos.terminar_todos(espera=1)  # no debe lanzar ProcessLookupError
    assert procesos._vivos == {}


# ── sesion(): se reutiliza sin volver a Tidal ────────────────────────────────


class _SesionFalsa:
    comprobaciones = 0

    def __init__(self):
        self.audio_quality = None

    def load_session_from_file(self, _):
        return True

    def check_login(self):
        _SesionFalsa.comprobaciones += 1
        return True


def _preparar_sesion(monkeypatch, tmp_path):
    archivo = tmp_path / "s.json"
    archivo.write_text("{}")
    monkeypatch.setattr(sesion, "SESSION_FILE", archivo)
    monkeypatch.setattr(sesion, "_guardar", lambda s: None)
    import tidalapi

    monkeypatch.setattr(tidalapi, "Session", _SesionFalsa)
    _SesionFalsa.comprobaciones = 0
    sesion.olvidar()


def test_sesion_se_reutiliza_dentro_de_la_vigencia(monkeypatch, tmp_path):
    _preparar_sesion(monkeypatch, tmp_path)
    a = sesion.sesion()
    b = sesion.sesion()
    assert a is b
    assert _SesionFalsa.comprobaciones == 1
    sesion.olvidar()


def test_sesion_se_comprueba_otra_vez_al_vencer(monkeypatch, tmp_path):
    _preparar_sesion(monkeypatch, tmp_path)
    sesion.sesion()
    reloj = time.monotonic() + sesion.VIGENCIA_SEGUNDOS + 1
    monkeypatch.setattr(sesion.time, "monotonic", lambda: reloj)
    sesion.sesion()
    assert _SesionFalsa.comprobaciones == 2
    sesion.olvidar()


def test_sesion_none_no_se_guarda(monkeypatch, tmp_path):
    _preparar_sesion(monkeypatch, tmp_path)
    sesion.SESSION_FILE.unlink()
    assert sesion.sesion() is None
    assert sesion._cache is None


# ── _Favoritos: solo las pistas descargadas ──────────────────────────────────


def _pista(tid, titulo, album):
    return SimpleNamespace(
        id=tid,
        title=titulo,
        version=None,
        album=SimpleNamespace(title=album),
        isrc=f"ISRC{tid}",
        audioModes=["STEREO"],
    )


class _ApiFalsa:
    def __init__(self, pistas, favoritos):
        self.pistas = pistas
        self.favoritos = favoritos
        self.pedidas: list = []

    def get_track(self, tid):
        self.pedidas.append(str(tid))
        return self.pistas[str(tid)]

    def get_favorites(self):
        return SimpleNamespace(model_dump=lambda: {"TRACK": self.favoritos})


def _indice(monkeypatch, ids):
    pistas = {str(i): _pista(i, f"Canción {i}", "Disco") for i in range(1, 11)}
    api = _ApiFalsa(pistas, list(range(1, 11)))
    fav = descargar._Favoritos(ids)
    monkeypatch.setattr(fav, "_api", lambda: api)
    return fav, api


def test_favoritos_con_ids_solo_pide_esas_pistas(monkeypatch):
    fav, api = _indice(monkeypatch, [2, 5])
    assert fav.buscar("Canción 5", "Disco").isrc == "ISRC5"
    assert sorted(api.pedidas) == ["2", "5"]


def test_favoritos_recurre_a_todos_si_no_encuentra(monkeypatch):
    fav, api = _indice(monkeypatch, [2])
    assert fav.buscar("Canción 7", "Disco").isrc == "ISRC7"  # resto de otra descarga
    assert len(api.pedidas) == 10  # la 2 no se vuelve a pedir
    fav.buscar("No existe", "Disco")
    assert len(api.pedidas) == 10  # el recorrido completo es una sola vez


def test_favoritos_sin_ids_recorre_todos(monkeypatch):
    fav, api = _indice(monkeypatch, None)
    assert fav.buscar_titulo("Canción 3")
    assert len(api.pedidas) == 10
