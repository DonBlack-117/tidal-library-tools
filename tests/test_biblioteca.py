from core import biblioteca


def _correr(gen):
    return list(gen)


def test_aplanar_mueve_audio_y_letras_sin_subcarpetas(tmp_path, flac):
    origen = flac(tmp_path / ".descarga" / "Artista" / "Disco" / "01 - Canción.flac", isrc="AAA111")
    origen.with_suffix(".lrc").write_text("[00:00.00] hola", encoding="utf-8")

    _correr(biblioteca.aplanar(tmp_path))

    canciones = list((tmp_path / "canciones").iterdir())
    assert [p.name for p in canciones] == ["Canción.flac"]  # sin número de pista
    assert (tmp_path / "lyrics" / "Canción.lrc").exists()
    assert not (tmp_path / ".descarga").exists()


def test_aplanar_descarta_lo_que_ya_estaba_por_isrc(tmp_path, flac):
    flac(tmp_path / "canciones" / "Artista - Canción.flac", isrc="AAA111")
    flac(tmp_path / ".descarga" / "x" / "01 - Otro nombre.flac", isrc="aaa111")

    lineas = _correr(biblioteca.aplanar(tmp_path))

    assert len(list((tmp_path / "canciones").iterdir())) == 1
    assert any("1 descartada" in line for line in lineas)


def test_isrcs_presentes_ignora_mayusculas_y_usa_cache(tmp_path, flac, monkeypatch):
    flac(tmp_path / "canciones" / "a.flac", isrc="abc123")
    assert biblioteca.isrcs_presentes(tmp_path) == {"ABC123"}

    llamadas = []
    original = biblioteca._leer_tags
    monkeypatch.setattr(biblioteca, "_leer_tags", lambda p: llamadas.append(p) or original(p))
    biblioteca.isrcs_presentes(tmp_path)
    assert llamadas == []  # el archivo no cambió: sale de la caché


def test_registrar_ids_guarda_isrc_en_mayusculas(tmp_path):
    biblioteca.registrar_ids(tmp_path, {"1": "abc", "2": ""})
    assert biblioteca._cargar_registro(tmp_path) == {"1": "ABC"}


def test_estadisticas_cuenta_hires(tmp_path, flac):
    flac(tmp_path / "canciones" / "a.flac", isrc="A")
    stats = biblioteca.estadisticas(tmp_path)
    assert stats["canciones"] == 1
    assert stats["hires"] == 0
