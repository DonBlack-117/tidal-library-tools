"""
Cualquier cosa que se pueda descargar: una canción, un álbum, una playlist, la
discografía de un artista, un mix o My Tracks.

1. `resolver` (o `mis_tracks`) pide a Tidal la lista de canciones con su ISRC.
2. `vista_previa` cuenta cuántas ya están en la biblioteca y cuántas faltan.
3. `descargar` baja solo las que faltan con tiddl y, si es una lista
   (playlist o mix), escribe su .m3u8.

Uso desde la terminal:
  python -m core.recursos mytracks [carpeta]
  python -m core.recursos "https://tidal.com/browse/album/123" [carpeta]
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from core import biblioteca, hires, playlists, sesion
from core import descargar as motor
from core.enlaces import ARTICULOS, NOMBRES, Enlace, interpretar

# Tipos que pueden ser muy grandes: la web pide confirmar antes de bajarlos
CONFIRMAR = {"artist", "mix"}
# Tipos que generan un .m3u8 con el orden de Tidal
CON_LISTA = {"playlist", "mix"}


class NoEncontrado(LookupError):
    """Tidal no tiene ese recurso (borrado, privado o de otra región)."""


@dataclass(frozen=True)
class Pista:
    id: int
    isrc: str
    titulo: str
    artista: str
    duracion: int
    disponible: bool

    @classmethod
    def desde_tidal(cls, t) -> "Pista":
        titulo = f"{t.name} ({t.version})" if getattr(t, "version", None) else t.name
        return cls(
            id=int(t.id),
            isrc=(t.isrc or "").upper(),
            titulo=titulo,
            artista=t.artist.name if getattr(t, "artist", None) else "",
            duracion=int(t.duration or 0),
            disponible=bool(getattr(t, "available", True)),
        )


@dataclass
class Recurso:
    tipo: str      # track | album | playlist | artist | mix | mytracks
    id: str
    nombre: str
    detalle: str   # artista, autor de la playlist o número de álbumes
    pistas: list[Pista] = field(default_factory=list)

    @property
    def requiere_confirmar(self) -> bool:
        return self.tipo in CONFIRMAR

    @property
    def tipo_legible(self) -> str:
        return "My Tracks" if self.tipo == "mytracks" else NOMBRES[self.tipo]


def _es_pista(objeto) -> bool:
    """tidalapi.Track o una subclase (un mix también trae videos)."""
    return any(c.__name__ == "Track" for c in type(objeto).__mro__)


def _paginar(pedir, tam: int = 100) -> list:
    """
    Pide todas las páginas de un método de tidalapi con (limit, offset).
    Algunos endpoints de Tidal cortan en 100 aunque se pidan más.
    """
    resultado, offset = [], 0
    while True:
        pagina = list(pedir(limit=tam, offset=offset))
        resultado.extend(pagina)
        if len(pagina) < tam:
            return resultado
        offset += tam


def _pistas(tracks) -> list[Pista]:
    """Solo pistas, sin repetir el mismo ISRC."""
    vistas, resultado = set(), []
    for t in tracks:
        if not _es_pista(t):
            continue
        p = Pista.desde_tidal(t)
        clave = p.isrc or p.id
        if clave in vistas:
            continue
        vistas.add(clave)
        resultado.append(p)
    return resultado


def _obtener(funcion, enlace: Enlace):
    """Llama a tidalapi y convierte su 404 en NoEncontrado."""
    from tidalapi.exceptions import ObjectNotFound

    try:
        return funcion(enlace.id)
    except ObjectNotFound as e:
        raise NoEncontrado(f"Tidal no tiene {ARTICULOS[enlace.tipo]} {NOMBRES[enlace.tipo]} "
                           "(puede que lo hayan quitado o no esté en tu región)") from e


def resolver(s, enlace: Enlace) -> Recurso:
    """Recurso con todas sus pistas, consultando a Tidal con la sesión `s`."""
    if enlace.tipo == "track":
        t = _obtener(s.track, enlace)
        return Recurso("track", enlace.id, t.name, t.artist.name if t.artist else "", _pistas([t]))

    if enlace.tipo == "album":
        a = _obtener(s.album, enlace)
        return Recurso("album", enlace.id, a.name, a.artist.name if a.artist else "", _pistas(_paginar(a.tracks)))

    if enlace.tipo == "playlist":
        p = _obtener(s.playlist, enlace)
        autor = getattr(getattr(p, "creator", None), "name", "") or ""
        # Tidal pone "me" como autor de las playlists propias
        autor = "tu playlist" if autor.lower() == "me" else autor
        return Recurso("playlist", enlace.id, p.name.strip(), autor, _pistas(p.tracks_paginated()))

    if enlace.tipo == "artist":
        a = _obtener(s.artist, enlace)
        albumes = _paginar(a.get_albums) + _paginar(a.get_ep_singles)
        # Una petición por álbum: en paralelo, la discografía tarda segundos y no minutos
        with ThreadPoolExecutor(max_workers=6) as pool:
            tracks = [t for lista in pool.map(lambda album: _paginar(album.tracks), albumes) for t in lista]
        return Recurso("artist", enlace.id, a.name, f"{len(albumes)} álbumes y sencillos", _pistas(tracks))

    m = _obtener(s.mix, enlace)
    return Recurso("mix", enlace.id, m.title, getattr(m, "sub_title", "") or "", _pistas(m.items()))


def mis_tracks(s) -> Recurso:
    """Todas las pistas favoritas de la cuenta."""
    return Recurso("mytracks", "", "My Tracks", "tus canciones favoritas",
                   _pistas(s.user.favorites.tracks_paginated()))


def pendientes(recurso: Recurso, base: Path) -> list[Pista]:
    """
    Pistas disponibles que no están en disco. Se comparan por ISRC; las pocas
    que Tidal da sin ISRC se comparan por artista y título, si no se bajarían
    otra vez en cada descarga.
    """
    presentes = biblioteca.isrcs_presentes(base)
    sin_isrc = [p for p in recurso.pistas if not p.isrc]
    titulos = biblioteca.titulos_presentes(base) if sin_isrc else set()
    return [p for p in recurso.pistas if p.disponible and (
        p.isrc not in presentes if p.isrc
        else biblioteca.clave_titulo(p.artista, p.titulo) not in titulos)]


def vista_previa(recurso: Recurso, base: Path) -> dict:
    """Lo que la web muestra antes de descargar."""
    faltan = pendientes(recurso, base)
    no_disponibles = sum(1 for p in recurso.pistas if not p.disponible)
    return {
        "tipo": recurso.tipo,
        "tipo_legible": recurso.tipo_legible,
        "id": recurso.id,
        "nombre": recurso.nombre,
        "detalle": recurso.detalle,
        "total": len(recurso.pistas),
        "ya_tienes": len(recurso.pistas) - len(faltan) - no_disponibles,
        "por_descargar": len(faltan),
        "no_disponibles": no_disponibles,
        "requiere_confirmar": recurso.requiere_confirmar,
        "crea_lista": recurso.tipo in CON_LISTA,
        "muestra": [f"{p.artista} - {p.titulo}" if p.artista else p.titulo for p in faltan[:5]],
    }


def canciones(recurso: Recurso, base: Path) -> list[dict]:
    """
    Todas las canciones con su estado, para la ventana de selección:
    "falta" (se puede descargar), "tienes" (ya en disco) o "no_disponible".
    """
    faltan = {p.id for p in pendientes(recurso, base)}
    return [{
        "id": p.id,
        "titulo": p.titulo,
        "artista": p.artista,
        "duracion": p.duracion,
        "estado": "no_disponible" if not p.disponible else "falta" if p.id in faltan else "tienes",
    } for p in recurso.pistas]


class SeleccionInvalida(ValueError):
    """Se pidieron canciones que no son de este recurso."""


def descargar(recurso: Recurso, base: Path, ids: list[int] | None = None):
    """
    Generador para SSE: descarga lo que falta y, si es una lista, escribe su
    .m3u8. Con `ids` solo baja esas canciones (las elegidas en la ventana de
    selección). Devuelve el código de salida.
    """
    if ids is not None:
        desconocidas = set(ids) - {p.id for p in recurso.pistas}
        if desconocidas:
            raise SeleccionInvalida(f"{len(desconocidas)} canción(es) no son de «{recurso.nombre}»")

    info = vista_previa(recurso, base)
    detalle = f" · {recurso.detalle}" if recurso.detalle else ""
    total = "1 canción" if info["total"] == 1 else f"{info['total']} canciones"
    yield f"▶ {recurso.tipo_legible.capitalize()} «{recurso.nombre}»{detalle}: {total}"

    faltan = pendientes(recurso, base)
    if ids is not None:
        elegidas = set(ids)
        faltan = [p for p in faltan if p.id in elegidas]
        ya = sum(1 for p in recurso.pistas if p.id in elegidas) - len(faltan)
        yield f"☑ {len(ids)} elegidas: {ya} ya descargadas, {len(faltan)} por descargar"
    else:
        # Las cifras con este formato las lee la web para el resumen y la barra de progreso
        yield (f"📋 {info['ya_tienes']} ya descargadas, {info['por_descargar']} por descargar, "
               f"{info['no_disponibles']} no disponibles en Tidal")

    # hires.mejorar busca el ID de Tidal por ISRC en este registro
    biblioteca.registrar_ids(base, {str(p.id): p.isrc for p in recurso.pistas})

    code = 0
    if faltan:
        code = yield from motor.descargar_pistas([p.id for p in faltan], base)
    else:
        yield "✅ Todo al día: no hay canciones nuevas"
        if recurso.tipo == "mytracks":
            # Por si quedó algo a medias en una ejecución anterior
            yield from biblioteca.aplanar(base)
            code = yield from hires.mejorar(base)

    if recurso.tipo in CON_LISTA:
        # Con una selección parcial la lista lleva lo que haya en disco; que falten otras no es error
        code_lista = yield from playlists.escribir_listas(base, recurso.nombre, recurso.pistas,
                                                           avisar_faltantes=ids is None)
        code = code or (code_lista if ids is None else 0)
    return code


def _main(argv: list[str]) -> int:
    if not argv:
        print('Uso: python -m core.recursos mytracks|"<link de Tidal>" [carpeta]')
        return 2
    base = Path(argv[1] if len(argv) > 1 else motor.DEFAULT_OUTPUT_DIR).expanduser()
    s = sesion.sesion()
    if s is None:
        print(f"❌ {sesion.SinSesion()}")
        return 1
    recurso = mis_tracks(s) if argv[0].lower() == "mytracks" else resolver(s, interpretar(argv[0]))
    gen = descargar(recurso, base)
    try:
        while True:
            print(next(gen), flush=True)
    except StopIteration as fin:
        return fin.value or 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
