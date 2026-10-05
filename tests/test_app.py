import json

import pytest

import app as servidor
from core import recursos

PLAYLIST = "36ea71a8-445e-41a4-82ab-6628c581535d"


@pytest.fixture
def client(fake_session, monkeypatch, tmp_path):
    monkeypatch.setattr(servidor.sesion, "sesion", lambda: fake_session)
    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: {"AAA111"})
    servidor._cache_recursos.clear()
    servidor.app.config["TESTING"] = True
    with servidor.app.test_client() as c:
        c.base_url = "http://localhost:5000"
        yield c


def post(client, ruta, datos=None, **kw):
    return client.post(ruta, json=datos or {}, base_url="http://localhost:5000", **kw)


def eventos(resp) -> list[dict]:
    texto = resp.get_data(as_text=True)
    return [json.loads(b[len("data: "):]) for b in texto.split("\n\n") if b.startswith("data: ")]


# ── Seguridad ─────────────────────────────────────────────────────────────────

def test_rechaza_otro_host(client):
    r = client.get("/", base_url="http://evil.example:5000")
    assert r.status_code == 403
    assert r.json["error"]["code"] == "HOST_NO_PERMITIDO"


def test_rechaza_post_desde_otra_pagina(client):
    r = post(client, "/shutdown", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json["error"]["code"] == "ORIGEN_NO_PERMITIDO"


def test_rechaza_post_que_no_es_json(client):
    r = client.post("/run/hires", data="x=1", content_type="application/x-www-form-urlencoded",
                    base_url="http://localhost:5000")
    assert r.status_code == 415


def test_acepta_post_de_la_propia_pagina(client, monkeypatch):
    monkeypatch.setattr(servidor, "_hay", lambda programa: False)
    r = post(client, "/pick-folder", headers={"Origin": "http://localhost:5000"})
    assert r.status_code == 501  # llegó a la ruta: no hay zenity en la prueba


# ── Vista previa ──────────────────────────────────────────────────────────────

def test_vista_previa_de_un_link_pegado(client):
    r = post(client, "/api/vista-previa", {"texto": f"Escucha en TIDAL https://tidal.com/playlist/{PLAYLIST}"})
    assert r.status_code == 200
    assert r.json["tipo"] == "playlist"
    assert r.json["nombre"] == "Mi lista"
    assert (r.json["ya_tienes"], r.json["por_descargar"], r.json["no_disponibles"]) == (1, 1, 1)


def test_vista_previa_de_my_tracks(client):
    r = post(client, "/api/vista-previa", {"mytracks": True})
    assert r.json["tipo"] == "mytracks"
    assert r.json["total"] == 3


@pytest.mark.parametrize("texto,status,code", [
    ("", 400, "ENLACE_INVALIDO"),
    ("https://open.spotify.com/track/1", 400, "ENLACE_INVALIDO"),
    ("https://tidal.com/browse/track/999", 404, "NO_ENCONTRADO"),
])
def test_vista_previa_errores(client, texto, status, code):
    r = post(client, "/api/vista-previa", {"texto": texto})
    assert r.status_code == status
    assert r.json["error"]["code"] == code


def test_sin_sesion(client, monkeypatch):
    monkeypatch.setattr(servidor.sesion, "sesion", lambda: None)
    r = post(client, "/api/vista-previa", {"texto": "track/1"})
    assert r.status_code == 401
    assert "core.hires login" in r.json["error"]["message"]


def test_la_vista_previa_queda_en_cache(client, fake_session, monkeypatch):
    post(client, "/api/vista-previa", {"texto": "track/1"})
    monkeypatch.setattr(fake_session, "track", lambda id: pytest.fail("debía usar la caché"))
    assert post(client, "/api/vista-previa", {"texto": "https://tidal.com/track/1"}).status_code == 200


# ── Descargar ─────────────────────────────────────────────────────────────────

def test_descarga_por_sse_con_codigo_real(client, monkeypatch):
    def falso(ids, base):
        yield f"Downloaded {ids}"
        return 0

    monkeypatch.setattr(recursos.motor, "descargar_pistas", falso)
    r = post(client, "/run/descargar", {"texto": "album/10"})

    ev = eventos(r)
    assert r.mimetype == "text/event-stream"
    assert any(e.get("line") == "Downloaded [2]" for e in ev)
    assert ev[-1] == {"done": True, "code": 0}


def test_artista_pide_confirmar(client):
    r = post(client, "/run/descargar", {"texto": "artist/20"})
    assert r.status_code == 409
    assert r.json["error"]["code"] == "CONFIRMAR"


def test_artista_confirmado_se_descarga(client, monkeypatch):
    monkeypatch.setattr(recursos.motor, "descargar_pistas", lambda ids, base: iter(()))
    r = post(client, "/run/descargar", {"texto": "artist/20", "confirmado": True})
    assert r.status_code == 200
    assert eventos(r)[-1]["done"] is True


def test_una_sola_operacion_a_la_vez(client):
    assert servidor._operacion.acquire(blocking=False)
    try:
        r = post(client, "/run/hires", {})
        assert r.status_code == 409
        assert r.json["error"]["code"] == "OCUPADO"
    finally:
        servidor._operacion.release()


def test_el_candado_se_suelta_al_terminar(client, monkeypatch):
    monkeypatch.setattr(recursos.motor, "descargar_pistas", lambda ids, base: iter(()))
    eventos(post(client, "/run/descargar", {"texto": "track/2"}))
    assert servidor._operacion.acquire(blocking=False)
    servidor._operacion.release()


def test_error_dentro_del_stream_termina_con_codigo_1(client, monkeypatch):
    def falla(ids, base):
        raise RuntimeError("tiddl explotó")
        yield  # pragma: no cover

    monkeypatch.setattr(recursos.motor, "descargar_pistas", falla)
    ev = eventos(post(client, "/run/descargar", {"texto": "track/2"}))
    assert any("tiddl explotó" in e.get("line", "") for e in ev)
    assert ev[-1] == {"done": True, "code": 1}


def test_herramienta_desconocida(client):
    assert post(client, "/run/borrar-todo", {}).status_code == 404


def test_playlists_sin_sesion(client, monkeypatch):
    monkeypatch.setattr("core.playlists.sesion.sesion", lambda: None)
    r = client.get("/playlists", base_url="http://localhost:5000")
    assert r.status_code == 401


def test_el_candado_se_suelta_aunque_el_stream_nunca_empiece(client):
    with servidor.app.test_request_context():
        resp = servidor._sse(linea for linea in ["nunca se lee"])
        assert servidor._operacion.locked()
        resp.close()
    assert not servidor._operacion.locked()


def test_detener_termina_el_proceso_y_sus_hijos(tmp_path):
    import os
    import sys

    marca = tmp_path / "hijo.pid"
    codigo = (f"import subprocess, sys, time; "
              f"h = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
              f"open({str(marca)!r}, 'w').write(str(h.pid)); print('listo', flush=True); time.sleep(60)")
    env = {**os.environ}
    modulo = tmp_path / "durmiente.py"
    modulo.write_text(codigo, encoding="utf-8")
    env["PYTHONPATH"] = str(tmp_path)
    g = servidor._proceso("durmiente", env, False)
    assert next(g) == "listo"
    g.close()  # lo que pasa al pulsar Detener

    hijo = int(marca.read_text())
    import time
    for _ in range(50):
        try:
            os.kill(hijo, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("el proceso hijo siguió vivo")


@pytest.mark.parametrize("cuerpo", [[1, 2], {"texto": 5}, {"texto": None}])
def test_cuerpos_raros_dan_json_y_no_500(client, cuerpo):
    r = client.post("/api/vista-previa", json=cuerpo, base_url="http://localhost:5000")
    assert r.status_code == 400
    assert r.json["error"]["code"] == "ENLACE_INVALIDO"


def test_rechaza_peticion_cross_site_por_sec_fetch(client):
    r = client.get("/playlists", base_url="http://localhost:5000", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_confirmado_debe_ser_true_literal(client):
    r = post(client, "/run/descargar", {"texto": "artist/20", "confirmado": "no"})
    assert r.status_code == 409


def test_lista_de_canciones(client):
    r = post(client, "/api/canciones", {"texto": f"https://tidal.com/playlist/{PLAYLIST}"})
    assert r.status_code == 200
    assert r.json["nombre"] == "Mi lista"
    assert [c["estado"] for c in r.json["canciones"]] == ["falta", "tienes", "no_disponible"]


def test_lista_de_my_tracks(client):
    r = post(client, "/api/canciones", {"mytracks": True})
    assert len(r.json["canciones"]) == 3


def test_descargar_solo_las_elegidas_por_sse(client, monkeypatch):
    pedidas = []

    def falso(ids, base):
        pedidas.extend(ids)
        yield "Downloaded"
        return 0

    monkeypatch.setattr(recursos.motor, "descargar_pistas", falso)
    ev = eventos(post(client, "/run/descargar", {"mytracks": True, "ids": [2]}))
    assert pedidas == [2]
    assert ev[-1] == {"done": True, "code": 0}


def test_elegidas_de_un_artista_no_piden_confirmar(client, monkeypatch):
    monkeypatch.setattr(recursos.motor, "descargar_pistas", lambda ids, base: iter(()))
    assert post(client, "/run/descargar", {"texto": "artist/20", "ids": [2]}).status_code == 200


@pytest.mark.parametrize("ids", [[], "2", [2.5], [True], [999]])
def test_seleccion_invalida(client, ids):
    r = post(client, "/run/descargar", {"mytracks": True, "ids": ids})
    assert r.status_code == 400
    assert r.json["error"]["code"] == "SELECCION_INVALIDA"
