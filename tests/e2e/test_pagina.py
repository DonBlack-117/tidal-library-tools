import re

import pytest
from playwright.sync_api import expect

import app as servidor
from tests.e2e.pagina import PaginaTidal

PLAYLIST = "36ea71a8-445e-41a4-82ab-6628c581535d"


@pytest.fixture
def pagina(page, app_url):
    p = PaginaTidal(page, app_url)
    p.abrir()
    return p


def test_vista_previa_al_pegar_un_link(pagina):
    pagina.revisar_link(f"Escucha Mi lista en TIDAL https://tidal.com/playlist/{PLAYLIST}/u")

    expect(pagina.vista).to_be_visible()
    expect(pagina.vista).to_contain_text("Mi lista")
    expect(pagina.vista).to_contain_text("tu playlist")
    expect(pagina.page.locator("#preview-pending")).to_have_text("1")
    expect(pagina.page.locator("#preview-have")).to_have_text("1")
    expect(pagina.page.locator("#preview-unavailable")).to_have_text("1")
    expect(pagina.descargar).to_have_text("Descargar 1 canción")


def test_pegar_con_ctrl_v_en_cualquier_parte(pagina):
    pagina.pegar_en_la_pagina("https://tidal.com/browse/album/10")

    expect(pagina.link).to_have_value("https://tidal.com/browse/album/10")
    expect(pagina.vista).to_contain_text("Disco")


def test_descargar_desde_la_vista_previa(pagina):
    pagina.revisar_link("https://tidal.com/browse/album/10")
    pagina.descargar.click()

    pagina.esperar_fin()
    expect(pagina.registro).to_contain_text("Downloaded pista 2")
    expect(pagina.resumen).to_contain_text("nuevas")
    expect(pagina.vista).to_be_hidden()
    expect(pagina.link).to_have_value("")


def test_artista_avisa_antes_de_bajar_la_discografia(pagina):
    pagina.revisar_link("https://tidal.com/browse/artist/20")

    expect(pagina.aviso).to_be_visible()
    expect(pagina.aviso).to_contain_text("discografía completa")
    expect(pagina.descargar).to_have_text("Sí, descargar 1 canción")
    pagina.descargar.click()
    pagina.esperar_fin()


def test_ya_tienes_todo_desactiva_el_boton(pagina):
    pagina.revisar_link("track/1")
    expect(pagina.descargar).to_have_text("Ya la tienes en tu biblioteca")
    expect(pagina.descargar).to_be_disabled()


@pytest.mark.parametrize("texto,mensaje", [
    ("https://open.spotify.com/track/1", "no es de Tidal"),
    ("https://tidal.com/browse/track/999", "Tidal no tiene esa canción"),
])
def test_errores_del_link(pagina, texto, mensaje):
    pagina.revisar_link(texto)
    expect(pagina.error).to_contain_text(mensaje)
    expect(pagina.vista).to_be_hidden()


def test_cambiar_el_texto_oculta_la_vista_previa_vieja(pagina):
    pagina.revisar_link("track/2")
    expect(pagina.vista).to_be_visible()
    pagina.link.fill("track/")
    expect(pagina.vista).to_be_hidden()


def test_my_tracks_dice_cuantas_faltan(pagina):
    expect(pagina.my_tracks_info).to_contain_text("3 favoritos · 1 nueva por descargar")


def test_my_tracks_abre_la_lista_con_su_estado(pagina):
    pagina.abrir_my_tracks()

    expect(pagina.ventana).to_be_visible()
    expect(pagina.filas).to_have_count(3)
    expect(pagina.cuentas).to_have_text("3 canciones · 1 falta · 1 en disco · 1 no disponible")
    expect(pagina.casilla("Dos")).to_be_enabled()
    expect(pagina.casilla("Uno")).to_be_disabled()     # ya está en disco
    expect(pagina.casilla("Tres")).to_be_disabled()    # no disponible
    expect(pagina.ventana).to_contain_text("en disco")
    expect(pagina.todo).to_have_text("Descargar todo (1 falta)")
    expect(pagina.seleccionadas).to_be_disabled()


def test_descargar_todo_desde_la_ventana(pagina):
    pagina.abrir_my_tracks()
    pagina.todo.click()

    expect(pagina.ventana).to_be_hidden()
    expect(pagina.page.locator("#op-title")).to_have_text("Descargando My Tracks")
    pagina.esperar_fin()
    expect(pagina.registro).to_contain_text("Downloaded pista 2")


def test_descargar_solo_las_seleccionadas(pagina):
    pagina.abrir_my_tracks()
    pagina.casilla("Dos").check()
    expect(pagina.seleccionadas).to_have_text("Descargar seleccionadas (1)")

    with pagina.page.expect_request(lambda r: "/run/descargar" in r.url) as pedido:
        pagina.seleccionadas.click()

    assert pedido.value.post_data_json["ids"] == [2]
    pagina.esperar_fin()
    expect(pagina.registro).to_contain_text("1 elegidas")


def test_buscar_y_marcar_las_que_faltan(pagina):
    pagina.abrir_my_tracks()
    pagina.buscar.fill("dós")   # sin importar acentos
    expect(pagina.filas.filter(visible=True)).to_have_count(1)
    expect(pagina.cuentas).to_contain_text("1 con la búsqueda")

    pagina.marcar.check()
    expect(pagina.seleccionadas).to_have_text("Descargar seleccionadas (1)")
    pagina.marcar.uncheck()
    expect(pagina.seleccionadas).to_be_disabled()


def test_escape_cierra_la_ventana(pagina):
    pagina.abrir_my_tracks()
    pagina.page.keyboard.press("Escape")
    expect(pagina.ventana).to_be_hidden()


def test_elegir_una_playlist_abre_sus_canciones(pagina):
    expect(pagina.playlists.locator("option")).to_have_count(2)
    with pagina.page.expect_response(lambda r: "/api/canciones" in r.url):
        pagina.playlists.select_option(PLAYLIST)

    expect(pagina.ventana).to_be_visible()
    expect(pagina.ventana).to_contain_text("Mi lista")
    expect(pagina.filas).to_have_count(3)


def test_elegir_canciones_desde_la_vista_previa(pagina):
    pagina.revisar_link("https://tidal.com/browse/album/10")
    with pagina.page.expect_response(lambda r: "/api/canciones" in r.url):
        pagina.elegir.click()
    expect(pagina.ventana).to_contain_text("Disco")


def test_una_cancion_no_ofrece_elegir(pagina):
    pagina.revisar_link("track/2")
    expect(pagina.elegir).to_be_hidden()


def test_otra_operacion_en_curso(pagina):
    pagina.revisar_link("track/2")
    assert servidor._operacion.acquire(blocking=False)
    try:
        pagina.descargar.click()
        expect(pagina.registro).to_contain_text("Ya hay una operación en curso")
        expect(pagina.estado).to_have_text("Finalizado con errores")
    finally:
        servidor._operacion.release()


def test_sin_peticiones_a_internet(page, app_url):
    externas = []
    page.on("request", lambda r: None if r.url.startswith(app_url) else externas.append(r.url))
    PaginaTidal(page, app_url).abrir()
    page.wait_for_load_state("networkidle")
    assert externas == []


def test_movil_sin_scroll_horizontal(page, app_url):
    page.set_viewport_size({"width": 390, "height": 844})
    PaginaTidal(page, app_url).abrir()
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0
    expect(page.get_by_test_id("link-input")).to_be_visible()
    assert re.search("Pega un link", page.content())
