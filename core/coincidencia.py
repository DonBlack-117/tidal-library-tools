"""
Normalización y firma de variante para comparar títulos de pistas de Tidal.

Dos herramientas borran o reemplazan favoritos de la cuenta real
(limpiar_duplicados y mejorar_calidad), así que la comparación de títulos
tiene que separar dos casos:

- Cambios que solo afectan al máster y no a la grabación (remaster, año,
  explicit/clean, mono/stereo): se ignoran, para que las dos copias se traten
  como el mismo tema y se puedan deduplicar.
- Cambios que marcan OTRA grabación distinta (live, acústica, remix, parte 1
  vs parte 2…): se conservan como «firma de variante», para no mezclar la
  versión en vivo con la de estudio ni «Parte 1» con «Parte 2».

`firma_variante` solo puede evitar agrupaciones; nunca fuerza una. Por eso
detectar de más es seguro (como mucho deja de deduplicar un par real), y
detectar de menos es lo peligroso (borra una grabación distinta).
"""

import re

# Palabras que solo cambian el máster, no la grabación: se quitan al comparar.
_RUIDO = [
    r"remaster(?:ed)?",
    r"digital remaster",
    r"anniversary",
    r"deluxe",
    r"bonus",
    r"album version",
    r"single version",
    r"radio edit",
    r"original",
    r"explicit",
    r"clean",
    r"mono",
    r"stereo",
    r"revisited",
    r"expanded",
    r"special edition",
    r"(?:19|20)\d{2}",  # años: 1999, 2011…
    r"\d+(?:st|nd|rd|th)",  # 25th, 1st…
]
_RUIDO_RE = re.compile(r"\b(?:" + "|".join(_RUIDO) + r")\b", re.IGNORECASE)

# Palabras que SÍ marcan otra grabación distinta de la original de estudio.
_VARIANTE_PALABRAS = [
    "live",
    "acoustic",
    "unplugged",
    "instrumental",
    "remix",
    "demo",
    "karaoke",
    "reprise",
    "rehearsal",
    "session",
    "sessions",
    "a cappella",
    "acapella",
    "rework",
]
_VARIANTE_RE = re.compile(
    r"\b(?:" + "|".join(p.replace(" ", r"\s+") for p in _VARIANTE_PALABRAS) + r")\b",
    re.IGNORECASE,
)
# Parte/volumen/acto con número (árabe o romano): «Part 1» ≠ «Part 2».
_PARTE_RE = re.compile(
    r"\b(?:part|pt|vol|volume|no|act)\.?\s*(\d+|[ivxlcdm]+)\b", re.IGNORECASE
)


def normalizar(texto: str) -> str:
    """
    Minúsculas, sin paréntesis ni corchetes, sin palabras de máster y sin
    símbolos. Dos másteres de la misma grabación dan el mismo texto.
    """
    texto = texto.lower()
    texto = re.sub(r"\(.*?\)", " ", texto)
    texto = re.sub(r"\[.*?\]", " ", texto)
    texto = _RUIDO_RE.sub(" ", texto)
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    return " ".join(texto.split())


def firma_variante(texto: str) -> frozenset:
    """
    Conjunto de rasgos que distinguen una grabación: palabras de variante
    (live, remix…) y números de parte. Se lee del texto completo, incluido lo
    que va entre paréntesis. Misma firma = puede ser el mismo tema; firma
    distinta = grabaciones diferentes que no deben mezclarse.
    """
    t = texto.lower()
    rasgos = {m.group(0).strip() for m in _VARIANTE_RE.finditer(t)}
    rasgos |= {f"parte:{m.group(1).lower()}" for m in _PARTE_RE.finditer(t)}
    return frozenset(rasgos)


def clave_cancion(artista: str, titulo: str) -> tuple | None:
    """
    Clave para agrupar o comparar: (artista_norm, titulo_norm, firma). Devuelve
    None si el título normaliza a vacío (p. ej. «1999» o «(Untitled)»): en ese
    caso no se puede comparar con seguridad y quien llama debe tratar la pista
    como única, nunca agruparla con otra.
    """
    titulo_norm = normalizar(titulo)
    if not titulo_norm:
        return None
    return (normalizar(artista), titulo_norm, firma_variante(titulo))
