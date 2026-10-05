import pytest

from core.enlaces import Enlace, EnlaceInvalido, interpretar

PLAYLIST = "36ea71a8-445e-41a4-82ab-6628c581535d"
MIX = "0164f9e4e1c7a7a3a4b7d1c08c8f3e"


@pytest.mark.parametrize("texto,esperado", [
    ("https://tidal.com/browse/track/77646169", Enlace("track", "77646169")),
    ("https://tidal.com/track/77646169/u", Enlace("track", "77646169")),
    ("https://tidal.com/browse/track/77646169?u", Enlace("track", "77646169")),
    ("https://listen.tidal.com/album/77646168", Enlace("album", "77646168")),
    ("tidal.com/browse/album/77646168/", Enlace("album", "77646168")),
    (f"https://tidal.com/playlist/{PLAYLIST}", Enlace("playlist", PLAYLIST)),
    (f"https://listen.tidal.com/playlist/{PLAYLIST.upper()}", Enlace("playlist", PLAYLIST)),
    ("https://tidal.com/browse/artist/3995478", Enlace("artist", "3995478")),
    (f"https://tidal.com/browse/mix/{MIX}", Enlace("mix", MIX)),
    ("https://tidal.com/browse/album/77646168/track/77646169", Enlace("album", "77646168")),
], ids=["browse", "share-u", "query", "listen", "sin-esquema", "playlist", "playlist-mayus",
        "artista", "mix", "primer-tipo"])
def test_urls(texto, esperado):
    assert interpretar(texto) == esperado


def test_texto_de_compartir_de_la_app():
    texto = "Escucha Tití Me Preguntó de Bad Bunny en TIDAL https://tidal.com/track/219389536/u"
    assert interpretar(texto) == Enlace("track", "219389536")


def test_link_entre_parentesis_o_con_punto_final():
    assert interpretar("(mira https://tidal.com/album/123.)") == Enlace("album", "123")


@pytest.mark.parametrize("texto,esperado", [
    ("track/123", Enlace("track", "123")),
    ("Album/456", Enlace("album", "456")),
    (f"playlist/{PLAYLIST}", Enlace("playlist", PLAYLIST)),
    ("tracks:789", Enlace("track", "789")),
    (PLAYLIST, Enlace("playlist", PLAYLIST)),
    ("  77646169  ", Enlace("track", "77646169")),
])
def test_atajos_e_ids(texto, esperado):
    assert interpretar(texto) == esperado


@pytest.mark.parametrize("texto,mensaje", [
    ("", "Pega un link"),
    ("   ", "Pega un link"),
    ("https://open.spotify.com/track/abc", "no es de Tidal"),
    ("hola", "No encontré"),
    ("https://tidal.com/browse/track/abc", "numérico"),
    ("https://tidal.com/browse/track/", "no trae ID"),
    ("https://tidal.com/browse/video/123", "no es de una canción"),
    ("https://tidal.com/playlist/123", "playlist no es válido"),
    ("https://tidal.com/mix/xyz", "mix no es válido"),
])
def test_textos_invalidos(texto, mensaje):
    with pytest.raises(EnlaceInvalido, match=mensaje):
        interpretar(texto)


def test_str_es_el_atajo_de_tiddl():
    assert str(Enlace("album", "1")) == "album/1"
