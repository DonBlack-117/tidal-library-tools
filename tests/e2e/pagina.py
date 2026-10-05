"""Page Object de la página principal."""

import re

from playwright.sync_api import Page, expect


class PaginaTidal:
    def __init__(self, page: Page, url: str):
        self.page = page
        self.url = url
        self.link = page.get_by_test_id("link-input")
        self.revisar = page.get_by_role("button", name="Revisar")
        self.error = page.get_by_test_id("link-error")
        self.vista = page.get_by_test_id("preview")
        self.descargar = page.get_by_test_id("preview-download")
        self.aviso = page.get_by_test_id("preview-warning")
        self.my_tracks = page.get_by_test_id("mytracks-btn")
        self.my_tracks_info = page.get_by_test_id("mytracks-info")
        self.playlists = page.get_by_test_id("playlist-select")
        self.registro = page.locator("#log-output")
        self.resumen = page.get_by_test_id("summary")
        self.estado = page.locator("#progress-status")
        self.elegir = page.get_by_test_id("preview-choose")
        self.ventana = page.get_by_test_id("songs-dialog")
        self.filas = page.get_by_test_id("songs-list").locator("li")
        self.todo = page.get_by_test_id("songs-all")
        self.seleccionadas = page.get_by_test_id("songs-selected")
        self.buscar = page.get_by_test_id("songs-search")
        self.marcar = page.get_by_test_id("songs-toggle")
        self.cuentas = page.get_by_test_id("songs-counts")

    def abrir(self):
        with self.page.expect_response(lambda r: "/api/vista-previa" in r.url):
            self.page.goto(self.url)

    def revisar_link(self, texto: str):
        self.link.fill(texto)
        with self.page.expect_response(lambda r: "/api/vista-previa" in r.url):
            self.revisar.click()

    def pegar_en_la_pagina(self, texto: str):
        """Ctrl+V fuera de los campos: se simula el evento paste con su portapapeles."""
        with self.page.expect_response(lambda r: "/api/vista-previa" in r.url):
            self.page.evaluate("""(texto) => {
                const data = new DataTransfer();
                data.setData('text', texto);
                document.body.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true }));
            }""", texto)

    def abrir_my_tracks(self):
        with self.page.expect_response(lambda r: "/api/canciones" in r.url):
            self.my_tracks.click()

    def casilla(self, titulo: str):
        return self.ventana.get_by_role("checkbox", name=re.compile(f"^{titulo} de"))

    def esperar_fin(self):
        expect(self.estado).to_have_text("Completado", timeout=10000)
