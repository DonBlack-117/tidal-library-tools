"""
Copia al teléfono (por adb) lo que falta de la biblioteca plana y las playlists.

- Canciones: <base>/canciones → carpeta del teléfono. Se copia lo que no existe
  allí o cuyo tamaño cambió (p. ej. mejorada a Hi-Res después de copiarla).
- Playlists: <base>/playlists/plana/*.m3u8 → la misma carpeta, junto a las
  canciones, para que Poweramp las importe.

No borra nada del teléfono, y tampoco vuelve a copiar lo que se borró allí:
<base>/.telefono_enviados.json guarda lo ya enviado; si un archivo enviado ya
no está en el teléfono, se considera borrado a propósito y se omite (salvo con
--reenviar-borrados). Requiere un solo dispositivo con depuración USB (o
inalámbrica) conectado.

Uso: python -m core.telefono [--simular] [--destino "/sdcard/Download/Quick Share"] [carpeta]
"""

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from core import biblioteca
from core.descargar import DEFAULT_OUTPUT_DIR

DESTINO = "/sdcard/Download/Quick Share"


class AdbNoDisponible(RuntimeError):
    """adb no está instalado, o no respondió a tiempo."""


# Timeouts: las órdenes cortas no deben colgar el servidor; push es más largo.
TIMEOUT_CORTO = 30
TIMEOUT_PUSH = 600


def _adb(
    *args: str, check: bool = True, timeout: int = TIMEOUT_CORTO
) -> subprocess.CompletedProcess:
    """
    Ejecuta adb con timeout. Si adb no está instalado o se cuelga, lanza
    AdbNoDisponible en vez de dejar bloqueado el hilo (y con él el candado de
    operación) para siempre.
    """
    try:
        return subprocess.run(
            ["adb", *args], capture_output=True, text=True, check=check, timeout=timeout
        )
    except FileNotFoundError:
        raise AdbNoDisponible("adb no está instalado (paquete android-tools)")
    except subprocess.TimeoutExpired:
        raise AdbNoDisponible(
            f"adb no respondió en {timeout}s (teléfono colgado o sin autorizar)"
        )


def _dispositivo() -> str | None:
    salida = _adb("devices", check=False).stdout.splitlines()[1:]
    listos = [l.split()[0] for l in salida if l.strip().endswith("device")]
    return listos[0] if len(listos) == 1 else None


def _archivos_telefono(serial: str, destino: str) -> dict[str, int]:
    """
    Nombre → tamaño en bytes de los archivos de la carpeta del teléfono.
    Lanza AdbNoDisponible si adb falla al listar: así no se confunde «la carpeta
    está vacía» con «adb se desconectó», que haría re-copiar toda la biblioteca.
    """
    # Un solo stat para todos (el shell expande * con los nombres tal cual);
    # uno por archivo tardaba ~20 s con 1000 canciones
    cmd = f"cd {shlex.quote(destino)} && stat -c '%s/%n' -- *"
    r = _adb("-s", serial, "shell", cmd, check=False)
    # stat devuelve != 0 si la carpeta no existe aún (primer envío) o si no hay
    # archivos; eso es un vacío legítimo. Pero si el error no es «No such file»,
    # algo falló (dispositivo desconectado) y no hay que fiarse del vacío.
    salida_err = (r.stderr or "").lower()
    if (
        r.returncode != 0
        and "no such file" not in salida_err
        and "no such" not in salida_err
    ):
        raise AdbNoDisponible(
            f"no se pudo listar el teléfono: {(r.stderr or r.stdout).strip()[:150]}"
        )
    archivos = {}
    for linea in r.stdout.splitlines():
        tam, _, nombre = linea.strip().partition("/")
        if tam.isdigit():
            archivos[nombre] = int(tam)
    return archivos


ENVIADOS = ".telefono_enviados.json"


def _leer_enviados(base: Path) -> dict[str, int] | None:
    try:
        return json.loads((base / ENVIADOS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _guardar_enviados(base: Path, enviados: dict[str, int]) -> None:
    tmp = base / (ENVIADOS + ".tmp")
    tmp.write_text(
        json.dumps(enviados, indent=0, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(base / ENVIADOS)


def _plan(base: Path, remotos: dict[str, int], reenviar_borrados: bool = False):
    """Qué falta copiar comparando la biblioteca con lo que hay en el teléfono."""
    carpeta = base / biblioteca.CANCIONES
    locales = sorted(p for p in carpeta.iterdir() if p.suffix in biblioteca.AUDIO_EXT) \
        if carpeta.is_dir() else []
    listas = sorted((base / "playlists" / "plana").glob("*.m3u8"))

    # Primer uso: lo que ya está en el teléfono cuenta como enviado
    enviados = _leer_enviados(base)
    if enviados is None:
        enviados = {p.name: remotos[p.name] for p in locales if p.name in remotos}

    borrados = [p for p in locales if p.name in enviados and p.name not in remotos]
    pendientes = [
        p
        for p in locales
        if remotos.get(p.name) != p.stat().st_size and (
            reenviar_borrados or p not in borrados
        )
    ]
    pendientes += [p for p in listas if remotos.get(p.name) != p.stat().st_size]
    return locales, listas, enviados, borrados, pendientes


def estado(base: Path, destino: str = DESTINO) -> dict:
    """Resumen para la web: teléfono conectado y cuánto falta por enviar (no copia nada)."""
    try:
        serial = _dispositivo()
        if serial is None:
            return {"ok": False}
        remotos = _archivos_telefono(serial, destino)
        _, _, _, borrados, pendientes = _plan(base, remotos)
        modelo = _adb(
            "-s", serial, "shell", "getprop ro.product.model", check=False
        ).stdout.strip()
    except AdbNoDisponible:
        return {"ok": False}
    return {
        "ok": True,
        "modelo": modelo or serial,
        "pendientes": len(pendientes),
        "borrados": len(borrados),
    }


def enviar(
    base: Path,
    destino: str = DESTINO,
    simular: bool = False,
    reenviar_borrados: bool = False,
):
    """Generador: copia lo que falta. Devuelve el código de salida."""
    try:
        serial = _dispositivo()
    except AdbNoDisponible as e:
        yield f"❌ {e}"
        return 1
    if serial is None:
        yield "❌ Conecta un solo teléfono con depuración USB activa (adb devices)"
        return 1

    try:
        _adb("-s", serial, "shell", f"mkdir -p {shlex.quote(destino)}", check=False)
        remotos = _archivos_telefono(serial, destino)
    except AdbNoDisponible as e:
        yield f"❌ {e}"
        return 1
    yield f"📱 {serial}: {len(remotos)} archivos en {destino}"

    locales, listas, enviados, borrados, pendientes = _plan(
        base, remotos, reenviar_borrados
    )
    nuevas = sum(p.name not in remotos for p in pendientes)
    yield (
        f"📋 {len(pendientes)} por copiar ({nuevas} nuevos, "
        f"{len(pendientes) - nuevas} actualizados), {len(listas)} playlist(s) revisadas"
    )
    if borrados and not reenviar_borrados:
        yield f"🗑 {len(borrados)} borrada(s) en el teléfono; no se vuelven a copiar:"
        for p in borrados[:20]:
            yield f"   · {p.name}"

    if simular:
        for p in pendientes:
            yield f"   · {p.name}"
        return 0

    errores = 0
    try:
        for n, p in enumerate(pendientes, 1):
            try:
                r = _adb(
                    "-s",
                    serial,
                    "push",
                    str(p),
                    f"{destino}/{p.name}",
                    check=False,
                    timeout=TIMEOUT_PUSH,
                )
            except AdbNoDisponible as e:
                errores += 1
                yield f"   ❌ {p.name}: {e}"
                continue
            if r.returncode != 0:
                errores += 1
                yield f"   ❌ {p.name}: {(r.stderr or r.stdout).strip()[-150:]}"
                continue
            if p.suffix in biblioteca.AUDIO_EXT:
                enviados[p.name] = p.stat().st_size
            yield f"   {n}/{len(pendientes)}"  # la web lo usa como barra de progreso
    finally:
        # Guardar siempre lo que sí se copió, aunque el usuario pulse Detener
        # (GeneratorExit) a mitad: si no, la próxima vez se re-copia todo.
        _guardar_enviados(base, enviados)

    # Comprobación final: lo local (menos lo borrado a propósito) debe estar igual en el teléfono
    try:
        remotos = _archivos_telefono(serial, destino)
    except AdbNoDisponible as e:
        yield f"⚠ No se pudo verificar el teléfono al final: {e}"
        return 1 if errores else 0
    omitir = set() if reenviar_borrados else {p.name for p in borrados}
    faltan = [
        p.name
        for p in locales + listas
        if p.name not in omitir and remotos.get(p.name) != p.stat().st_size
    ]
    if faltan:
        yield f"⚠ {len(faltan)} archivo(s) siguen distintos en el teléfono:"
        for nombre in faltan[:20]:
            yield f"   {nombre}"
    yield f"✅ Copiados {len(pendientes) - errores}; abre Poweramp → Ajustes → Library → Rescan si no aparecen"
    return 1 if (errores or faltan) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("carpeta", nargs="?", default=DEFAULT_OUTPUT_DIR)
    ap.add_argument("--destino", default=DESTINO)
    ap.add_argument(
        "--simular", action="store_true", help="solo muestra lo que copiaría"
    )
    ap.add_argument(
        "--reenviar-borrados",
        action="store_true",
        help="vuelve a copiar también lo que se borró en el teléfono",
    )
    args = ap.parse_args()
    gen = enviar(
        Path(args.carpeta).expanduser(),
        args.destino,
        args.simular,
        args.reenviar_borrados,
    )
    try:
        while True:
            print(next(gen), flush=True)
    except StopIteration as fin:
        sys.exit(fin.value or 0)
