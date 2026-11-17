"""Pruebas de la coincidencia local → Tidal de sincronizar (evita añadir pistas incorrectas)."""

from types import SimpleNamespace

from core.sincronizar import find_best_match


def _t(id, name, artist="The Beatles"):
    return SimpleNamespace(id=id, name=name, artist=SimpleNamespace(name=artist))


def test_no_confunde_subcadena_de_titulo():
    # "Love" no debe coincidir con "Love Me Do".
    resultados = [_t(1, "Love Me Do")]
    assert find_best_match(resultados, "The Beatles", "Love") is None


def test_titulo_vacio_no_coincide():
    resultados = [_t(1, "Cualquier cosa")]
    assert find_best_match(resultados, "Artista", "(Intro)") is None


def test_no_cambia_estudio_por_live():
    resultados = [_t(1, "Yesterday (Live)")]
    assert find_best_match(resultados, "The Beatles", "Yesterday") is None


def test_coincidencia_exacta_si():
    resultados = [_t(5, "Yesterday")]
    elegido = find_best_match(resultados, "The Beatles", "Yesterday")
    assert elegido is not None and elegido.id == 5


def test_coincidencia_ignora_remaster():
    # El local "Yesterday" debe coincidir con "Yesterday (Remastered 2009)".
    resultados = [_t(7, "Yesterday (Remastered 2009)")]
    elegido = find_best_match(resultados, "The Beatles", "Yesterday")
    assert elegido is not None and elegido.id == 7
