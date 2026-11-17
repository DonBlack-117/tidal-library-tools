"""
Pruebas de la lógica que decide si dos pistas son la misma grabación.

Estas pruebas blindan los dos arreglos más delicados: que limpiar_duplicados
no agrupe (y borre) grabaciones distintas, y que mejorar_calidad no reemplace
el estudio por una versión en vivo.
"""

from types import SimpleNamespace

from core import coincidencia
from core.limpiar_duplicados import find_duplicates


def _track(id, name, artist="Artista", quality="LOSSLESS"):
    return SimpleNamespace(
        id=id,
        name=name,
        artist=SimpleNamespace(name=artist),
        album=SimpleNamespace(name="Álbum"),
        audio_quality=quality,
    )


# ── Normalización y firma ────────────────────────────────────────────────────


def test_normalizar_ignora_master():
    # Remaster, año y explicit son el mismo tema: deben normalizar igual.
    assert coincidencia.normalizar("Song (Remastered 2011)") == coincidencia.normalizar(
        "Song"
    )
    assert coincidencia.normalizar("Song (Explicit)") == coincidencia.normalizar("Song")


def test_firma_distingue_live_de_estudio():
    assert coincidencia.firma_variante("Song") != coincidencia.firma_variante(
        "Song (Live)"
    )
    assert coincidencia.firma_variante("Song") != coincidencia.firma_variante(
        "Song (Acoustic)"
    )
    assert coincidencia.firma_variante("Song (Remix)") != coincidencia.firma_variante(
        "Song"
    )


def test_firma_distingue_partes():
    assert coincidencia.firma_variante("Intro (Part 1)") != coincidencia.firma_variante(
        "Intro (Part 2)"
    )


def test_clave_none_para_titulo_vacio():
    assert coincidencia.clave_cancion("Artista", "1999") is None
    assert coincidencia.clave_cancion("Artista", "(Untitled)") is None
    assert coincidencia.clave_cancion("Artista", "Song") is not None


# ── find_duplicates no agrupa grabaciones distintas ──────────────────────────


def test_live_no_se_agrupa_con_estudio():
    tracks = [_track(1, "Song"), _track(2, "Song (Live)")]
    assert find_duplicates(tracks) == {}


def test_partes_no_se_agrupan():
    tracks = [_track(1, "Intro (Part 1)"), _track(2, "Intro (Part 2)")]
    assert find_duplicates(tracks) == {}


def test_titulos_vacios_no_se_agrupan():
    # "1999" y "(Untitled)" normalizan a vacío: no deben caer en un grupo.
    tracks = [_track(1, "1999"), _track(2, "(Untitled)")]
    assert find_duplicates(tracks) == {}


def test_duplicado_real_si_se_agrupa():
    # Mismo tema, distinto máster: sí es duplicado.
    tracks = [_track(1, "Song"), _track(2, "Song (Remastered 2011)")]
    dupes = find_duplicates(tracks)
    assert len(dupes) == 1
    (grupo,) = dupes.values()
    assert len(grupo) == 2
