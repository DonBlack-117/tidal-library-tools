import pytest

from core import recursos
from core.enlaces import Enlace

PLAYLIST = "36ea71a8-445e-41a4-82ab-6628c581535d"
MIX = "0164f9e4e1c7a7a3a4b7d1c08c8f3e"


def test_cancion(fake_session):
    r = recursos.resolver(fake_session, Enlace("track", "2"))
    assert (r.tipo, r.nombre, r.detalle) == ("track", "Dos", "Artista")
    assert [p.isrc for p in r.pistas] == ["BBB222"]
    assert not r.requiere_confirmar


def test_album(fake_session):
    r = recursos.resolver(fake_session, Enlace("album", "10"))
    assert [p.titulo for p in r.pistas] == ["Uno", "Dos"]


def test_playlist_propia_sin_espacios_y_en_orden(fake_session):
    r = recursos.resolver(fake_session, Enlace("playlist", PLAYLIST))
    assert r.nombre == "Mi lista"
    assert r.detalle == "tu playlist"
    assert [p.id for p in r.pistas] == [2, 1, 3]


def test_artista_junta_albumes_y_sencillos_sin_repetir_isrc(fake_session):
    r = recursos.resolver(fake_session, Enlace("artist", "20"))
    assert r.detalle == "2 álbumes y sencillos"
    assert sorted(p.isrc for p in r.pistas) == ["AAA111", "BBB222"]
    assert r.requiere_confirmar


def test_mix_ignora_videos(fake_session):
    r = recursos.resolver(fake_session, Enlace("mix", MIX))
    assert [p.id for p in r.pistas] == [1, 2]
    assert r.requiere_confirmar


def test_no_encontrado_con_articulo_correcto(fake_session):
    with pytest.raises(recursos.NoEncontrado, match="Tidal no tiene esa canción"):
        recursos.resolver(fake_session, Enlace("track", "999"))
    with pytest.raises(recursos.NoEncontrado, match="Tidal no tiene ese álbum"):
        recursos.resolver(fake_session, Enlace("album", "999"))


def test_mis_tracks_quita_duplicados(fake_session):
    r = recursos.mis_tracks(fake_session)
    assert r.tipo_legible == "My Tracks"
    assert [p.id for p in r.pistas] == [1, 2, 3]


def test_vista_previa_cuenta_lo_que_ya_tienes(fake_session, monkeypatch, tmp_path):
    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: {"AAA111"})
    r = recursos.resolver(fake_session, Enlace("playlist", PLAYLIST))

    v = recursos.vista_previa(r, tmp_path)

    assert v["total"] == 3
    assert v["ya_tienes"] == 1
    assert v["por_descargar"] == 1
    assert v["no_disponibles"] == 1
    assert v["crea_lista"] is True
    assert v["muestra"] == ["Artista - Dos"]


def _correr(gen):
    lineas = []
    try:
        while True:
            lineas.append(next(gen))
    except StopIteration as fin:
        return lineas, fin.value


def test_descargar_solo_baja_lo_que_falta_y_registra_ids(fake_session, monkeypatch, tmp_path):
    pedidas = []

    def falso_descargar(ids, base):
        pedidas.extend(ids)
        yield "Downloaded algo"
        return 0

    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: {"AAA111"})
    monkeypatch.setattr(recursos.motor, "descargar_pistas", falso_descargar)
    r = recursos.resolver(fake_session, Enlace("album", "10"))

    lineas, code = _correr(recursos.descargar(r, tmp_path))

    assert pedidas == [2]
    assert code == 0
    assert "1 ya descargadas, 1 por descargar, 0 no disponibles" in lineas[1]
    assert recursos.biblioteca._cargar_registro(tmp_path) == {"1": "AAA111", "2": "BBB222"}


def test_descargar_sin_pendientes_no_llama_a_tiddl(fake_session, monkeypatch, tmp_path):
    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: {"AAA111", "BBB222"})
    monkeypatch.setattr(recursos.motor, "descargar_pistas", lambda *a: pytest.fail("no debía descargar"))
    r = recursos.resolver(fake_session, Enlace("track", "2"))

    lineas, code = _correr(recursos.descargar(r, tmp_path))

    assert code == 0
    assert "Todo al día" in lineas[-1]


def test_playlist_escribe_m3u8_con_el_orden_de_tidal(fake_session, monkeypatch, tmp_path):
    canciones = tmp_path / "canciones"
    canciones.mkdir()
    for nombre in ("Artista - Uno.flac", "Artista - Dos.flac"):
        (canciones / nombre).write_bytes(b"")
    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: {"AAA111", "BBB222"})
    monkeypatch.setattr(recursos.playlists, "_archivos_por_isrc",
                        lambda base: {"AAA111": canciones / "Artista - Uno.flac",
                                      "BBB222": canciones / "Artista - Dos.flac"})
    r = recursos.resolver(fake_session, Enlace("playlist", PLAYLIST))

    lineas, code = _correr(recursos.descargar(r, tmp_path))

    m3u = (tmp_path / "playlists" / "Mi lista.m3u8").read_text(encoding="utf-8").splitlines()
    assert m3u == ["#EXTM3U",
                   "#EXTINF:200,Artista - Dos", "../canciones/Artista - Dos.flac",
                   "#EXTINF:200,Artista - Uno", "../canciones/Artista - Uno.flac"]
    plana = (tmp_path / "playlists" / "plana" / "Mi lista.m3u8").read_text(encoding="utf-8")
    assert "\nArtista - Dos.flac\n" in plana
    # La que no está disponible se avisa, pero no es error
    assert code == 0
    assert any("no disponible en Tidal" in line for line in lineas)


def test_paginar_pide_hasta_la_ultima_pagina():
    from tests.conftest import paginado

    pedidas = []
    base = paginado(list(range(250)))

    def pedir(limit, offset):
        pedidas.append(offset)
        return base(limit=limit, offset=offset)

    assert recursos._paginar(pedir) == list(range(250))
    assert pedidas == [0, 100, 200]


def test_album_de_mas_de_100_canciones(fake_session):
    from tests.conftest import Track, paginado

    grande = [Track(1000 + i, f"Pista {i}", f"ISRC{i:04d}") for i in range(130)]
    fake_session.albums["11"] = fake_session.albums["10"].__class__(
        name="Caja", artist=None, tracks=paginado(grande))

    assert len(recursos.resolver(fake_session, Enlace("album", "11")).pistas) == 130


def test_pista_sin_isrc_se_compara_por_artista_y_titulo(monkeypatch, tmp_path):
    from tests.conftest import Track

    r = recursos.Recurso("album", "1", "Disco", "", recursos._pistas([
        Track(7, "Canción Sin Código", "", artist="Artísta"),
        Track(8, "Otra", "", artist="Artista")]))
    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: set())
    monkeypatch.setattr(recursos.biblioteca, "titulos_presentes",
                        lambda base: {recursos.biblioteca.clave_titulo("artista", "cancion sin codigo")})

    assert [p.id for p in recursos.pendientes(r, tmp_path)] == [8]


def test_subclases_de_track_cuentan_como_pistas():
    from tests.conftest import Track

    class TrackDeTidal(Track):
        pass

    assert [p.id for p in recursos._pistas([TrackDeTidal(5, "X", "Z5")])] == [5]


def test_canciones_con_su_estado(fake_session, monkeypatch, tmp_path):
    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: {"AAA111"})
    r = recursos.resolver(fake_session, Enlace("playlist", PLAYLIST))

    lista = recursos.canciones(r, tmp_path)

    assert [(c["id"], c["estado"]) for c in lista] == [(2, "falta"), (1, "tienes"), (3, "no_disponible")]
    assert lista[0] == {"id": 2, "titulo": "Dos", "artista": "Artista", "duracion": 200, "estado": "falta"}


def test_descargar_solo_las_elegidas(fake_session, monkeypatch, tmp_path):
    from tests.conftest import Track

    fake_session.albums["12"] = fake_session.albums["10"].__class__(
        name="Tres", artist=None, tracks=lambda limit=None, offset=0: [
            Track(21, "A", "I21"), Track(22, "B", "I22"), Track(23, "C", "I23")][offset:])
    pedidas = []

    def falso(ids, base):
        pedidas.extend(ids)
        return 0
        yield  # pragma: no cover

    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: set())
    monkeypatch.setattr(recursos.motor, "descargar_pistas", falso)
    r = recursos.resolver(fake_session, Enlace("album", "12"))

    lineas, code = _correr(recursos.descargar(r, tmp_path, ids=[23, 21]))

    assert pedidas == [21, 23]  # en el orden del álbum
    assert code == 0
    assert "2 elegidas: 0 ya descargadas, 2 por descargar" in lineas[1]


def test_descargar_rechaza_ids_ajenos(fake_session, tmp_path):
    r = recursos.resolver(fake_session, Enlace("album", "10"))
    with pytest.raises(recursos.SeleccionInvalida):
        next(recursos.descargar(r, tmp_path, ids=[999]))


def test_seleccion_parcial_de_playlist_no_es_error(fake_session, monkeypatch, tmp_path):
    monkeypatch.setattr(recursos.biblioteca, "isrcs_presentes", lambda base: set())
    monkeypatch.setattr(recursos.motor, "descargar_pistas", lambda ids, base: iter(()))
    monkeypatch.setattr(recursos.playlists, "_archivos_por_isrc", lambda base: {})
    r = recursos.resolver(fake_session, Enlace("playlist", PLAYLIST))

    lineas, code = _correr(recursos.descargar(r, tmp_path, ids=[2]))

    assert code == 0
    assert not any("sin archivo" in line for line in lineas)
    assert (tmp_path / "playlists" / "Mi lista.m3u8").exists()
