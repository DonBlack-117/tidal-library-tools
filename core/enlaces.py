"""
Interpreta lo que el usuario pega: un link de Tidal, el texto de «Compartir»
de la app («Escucha … en TIDAL https://tidal.com/track/123/u»), un atajo
`tipo/id` o solo el ID.

    >>> interpretar("https://tidal.com/browse/track/77646169?u")
    Enlace(tipo='track', id='77646169')
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

TIPOS = ("track", "album", "playlist", "artist", "mix")
NOMBRES = {
    "track": "canción",
    "album": "álbum",
    "playlist": "playlist",
    "artist": "artista",
    "mix": "mix",
}
# «esa canción», «ese álbum»: para los mensajes de error
ARTICULOS = {"track": "esa", "album": "ese", "playlist": "esa", "artist": "ese", "mix": "ese"}

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_URL = re.compile(r"(?:https?://)?(?:[a-z0-9-]+\.)*tidal\.com/\S+", re.I)
_ATAJO = re.compile(rf"\b({'|'.join(TIPOS)})s?[/:](\w[\w-]*)", re.I)
# Los IDs de mix son hexadecimales de 30 caracteres (a veces más)
_MIX_ID = re.compile(r"^[0-9a-f]{20,}$", re.I)


class EnlaceInvalido(ValueError):
    """El texto no contiene nada que se pueda descargar."""


@dataclass(frozen=True)
class Enlace:
    tipo: str
    id: str

    def __str__(self) -> str:
        return f"{self.tipo}/{self.id}"


def _validar(tipo: str, id_: str) -> Enlace:
    tipo = tipo.lower().rstrip("s")
    if tipo not in TIPOS:
        raise EnlaceInvalido(f"Tidal no tiene «{tipo}» que se pueda descargar")
    if tipo in ("track", "album", "artist") and not id_.isdigit():
        raise EnlaceInvalido(f"El ID de {NOMBRES[tipo]} debe ser numérico: {id_}")
    if tipo == "playlist":
        if not re.fullmatch(_UUID, id_, re.I):
            raise EnlaceInvalido(f"El ID de playlist no es válido: {id_}")
        id_ = id_.lower()
    if tipo == "mix" and not _MIX_ID.match(id_):
        raise EnlaceInvalido(f"El ID de mix no es válido: {id_}")
    return Enlace(tipo, id_)


def _desde_url(url: str) -> Enlace:
    if "://" not in url:
        url = "https://" + url
    # El link de «Compartir» puede terminar en punto o paréntesis del texto
    segmentos = [s for s in urlparse(url.rstrip(".,;)»\"'")).path.split("/") if s]
    for i, seg in enumerate(segmentos):
        if seg.lower() in TIPOS:
            if i + 1 >= len(segmentos):
                raise EnlaceInvalido(f"El link de {NOMBRES[seg.lower()]} no trae ID")
            return _validar(seg, segmentos[i + 1])
    raise EnlaceInvalido("El link de Tidal no es de una canción, álbum, playlist, artista o mix")


def interpretar(texto: str) -> Enlace:
    """Devuelve el Enlace del texto o lanza EnlaceInvalido con un mensaje para el usuario."""
    texto = (texto or "").strip()
    if not texto:
        raise EnlaceInvalido("Pega un link de Tidal")

    url = _URL.search(texto)
    if url:
        return _desde_url(url.group(0))
    if re.search(r"https?://", texto):
        raise EnlaceInvalido("Ese link no es de Tidal")

    atajo = _ATAJO.search(texto)
    if atajo:
        return _validar(atajo.group(1), atajo.group(2))

    if re.fullmatch(_UUID, texto, re.I):
        return Enlace("playlist", texto.lower())
    if texto.isdigit():
        return Enlace("track", texto)

    raise EnlaceInvalido("No encontré un link de Tidal en el texto pegado")
