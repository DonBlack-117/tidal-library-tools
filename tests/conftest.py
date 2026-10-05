"""Sesión de Tidal falsa y utilidades comunes de las pruebas."""

import subprocess
import shutil
from types import SimpleNamespace

import pytest


class Track:
    """Imita tidalapi.Track: recursos._pistas filtra por el nombre de la clase."""

    def __init__(self, id, name, isrc, artist="Artista", available=True, version=None, duration=200):
        self.id = id
        self.name = name
        self.isrc = isrc
        self.artist = SimpleNamespace(name=artist)
        self.available = available
        self.version = version
        self.duration = duration


class Video:
    def __init__(self, id):
        self.id = id


def paginado(items):
    """Imita los métodos de tidalapi que aceptan limit y offset."""
    def pedir(limit=None, offset=0):
        lista = list(items() if callable(items) else items)
        return lista[offset:offset + limit] if limit else lista[offset:]
    return pedir


class FakeSession:
    def __init__(self):
        self.tracks = {
            1: Track(1, "Uno", "AAA111"),
            2: Track(2, "Dos", "BBB222"),
            3: Track(3, "Tres", "CCC333", available=False),
            4: Track(4, "Uno", "AAA111"),  # misma grabación con otro ID
        }
        album = SimpleNamespace(name="Disco", artist=SimpleNamespace(name="Artista"),
                                tracks=paginado(lambda: [self.tracks[1], self.tracks[2]]))
        single = SimpleNamespace(name="Sencillo", tracks=paginado(lambda: [self.tracks[4]]))
        self.albums = {"10": album}
        self.playlists = {
            "36ea71a8-445e-41a4-82ab-6628c581535d": SimpleNamespace(
                name=" Mi lista ", creator=SimpleNamespace(name="me"),
                tracks_paginated=lambda: [self.tracks[2], self.tracks[1], self.tracks[3]]),
        }
        self.artists = {"20": SimpleNamespace(name="Artista", get_albums=paginado([album]),
                                              get_ep_singles=paginado([single]))}
        self.mixes = {"0164f9e4e1c7a7a3a4b7d1c08c8f3e": SimpleNamespace(
            title="Mix diario", sub_title="Para ti",
            items=lambda: [self.tracks[1], Video(99), self.tracks[2]])}
        self.user = SimpleNamespace(
            playlists=lambda: [SimpleNamespace(id="36ea71a8-445e-41a4-82ab-6628c581535d", name=" Mi lista ", num_tracks=3)],
            favorites=SimpleNamespace(
                playlists=lambda: [],
                tracks_paginated=lambda: [self.tracks[1], self.tracks[2], self.tracks[3], self.tracks[4]]))

    def _buscar(self, tabla, clave, tipo):
        from tidalapi.exceptions import ObjectNotFound

        try:
            return tabla[clave]
        except KeyError:
            raise ObjectNotFound(f"{tipo} {clave} not found") from None

    def track(self, id):
        return self._buscar(self.tracks, int(id), "Track")

    def album(self, id):
        return self._buscar(self.albums, id, "Album")

    def playlist(self, id):
        return self._buscar(self.playlists, id, "Playlist")

    def artist(self, id):
        return self._buscar(self.artists, id, "Artist")

    def mix(self, id):
        return self._buscar(self.mixes, id, "Mix")


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def flac(tmp_path):
    """Crea un FLAC real de 0.1 s con las etiquetas dadas."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg no está instalado")
    from mutagen.flac import FLAC

    def crear(ruta, isrc="", title="Canción", artist="Artista", album="Disco"):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                        "-t", "0.1", "-c:a", "flac", "-y", str(ruta)], check=True)
        f = FLAC(ruta)
        f["title"], f["artist"], f["album"] = title, artist, album
        if isrc:
            f["isrc"] = isrc
        f.save()
        return ruta

    return crear
