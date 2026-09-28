"""
Ejecuta tiddl pidiendo a Tidal la mezcla estéreo de las pistas que también
tienen Dolby Atmos.

Tidal devuelve solo el stream Atmos de esas pistas salvo que la petición
incluya `immersiveaudio=false` (parámetro normal de la API que elige la
mezcla; no toca cifrado ni DRM). tiddl 3.4.3 no lo envía, así que aquí se
añade y luego se lanza la CLI de tiddl sin más cambios.

Uso: python -m core.tiddl_estereo download -q max -da none -p <dir> fav -t track
"""

import sys

from tiddl.core.api import TidalAPI
from tiddl.core.api.api import DO_NOT_CACHE
from tiddl.core.api.models import TrackStream


def _get_track_stream_estereo(self, track_id, quality):
    return self.client.fetch(
        TrackStream,
        f"tracks/{track_id}/playbackinfopostpaywall",
        {
            "audioquality": quality,
            "playbackmode": "STREAM",
            "assetpresentation": "FULL",
            "immersiveaudio": "false",
        },
        expire_after=DO_NOT_CACHE,
    )


TidalAPI.get_track_stream = _get_track_stream_estereo

if __name__ == "__main__":
    from tiddl.cli.app import app

    sys.argv[0] = "tiddl"
    sys.exit(app())
