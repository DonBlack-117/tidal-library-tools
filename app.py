#!/usr/bin/env python3
"""
Servidor web local de Tidal Library Tools: http://localhost:5000

    .venv/bin/python app.py

Las operaciones largas (descargas, Hi-Res, teléfono, herramientas de My Tracks)
responden con Server-Sent Events: una línea de registro por evento y al final
{"done": true, "code": N}. Solo corre una a la vez.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from core import sesion
from core.enlaces import EnlaceInvalido, interpretar

app = Flask(__name__)
BASE_DIR = Path(__file__).parent
PUERTO = int(os.environ.get("TIDAL_TOOLS_PORT", "5000"))
HOSTS_PERMITIDOS = {"localhost", "127.0.0.1"}

# Herramientas de consola que trabajan sobre la cuenta (se corren como módulo)
SCRIPTS = {
    "sync": "core.sincronizar",
    "quality": "core.mejorar_calidad",
    "dupes": "core.limpiar_duplicados",
}
# Piden "si" a mitad de la ejecución; el clic en Ejecutar ya es la confirmación
AUTO_CONFIRM = {"quality", "dupes"}

# Una sola operación a la vez: todas escriben en la misma biblioteca
_operacion = threading.Lock()

# El recurso que se vio en la vista previa, para no pedirlo otra vez a Tidal al descargar
_CACHE_SEGUNDOS = 300
_cache_recursos: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()


def _hay(programa: str) -> bool:
    """True si el programa está instalado (adb, zenity…). Las pruebas lo reemplazan."""
    return shutil.which(programa) is not None


def error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


# ── Seguridad: solo esta página puede usar el servidor ────────────────────────

@app.before_request
def solo_local():
    """
    Cualquier página abierta en el navegador puede mandar peticiones a
    localhost:5000. Se rechazan las que vienen de otro origen, las de otro Host
    (DNS rebinding) y los POST que no son JSON (un formulario ajeno no puede
    mandar JSON sin que el navegador lo bloquee antes).
    """
    if (request.host.split(":")[0]) not in HOSTS_PERMITIDOS:
        return error("HOST_NO_PERMITIDO", "Solo se acepta localhost", 403)
    if request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
        return error("ORIGEN_NO_PERMITIDO", "Petición de otra página", 403)
    if request.method == "POST":
        origen = request.headers.get("Origin")
        if origen and urlparse(origen).netloc != request.host:
            return error("ORIGEN_NO_PERMITIDO", "Petición de otra página", 403)
        if not request.is_json:
            return error("SE_ESPERABA_JSON", "Las peticiones POST deben ser JSON", 415)
    return None


def _datos() -> dict:
    datos = request.get_json(silent=True)
    return datos if isinstance(datos, dict) else {}


def _texto(datos: dict, clave: str) -> str:
    valor = datos.get(clave)
    return valor if isinstance(valor, str) else ""


def _base(valor: str | None) -> Path:
    from core.descargar import DEFAULT_OUTPUT_DIR

    return Path((valor or "").strip() or DEFAULT_OUTPUT_DIR).expanduser()


# ── SSE ───────────────────────────────────────────────────────────────────────

def _evento(datos: dict) -> str:
    return f"data: {json.dumps(datos, ensure_ascii=False)}\n\n"


def _sse_generador(gen):
    """Convierte un generador de líneas en eventos SSE y envía el código de salida real."""
    code = 1
    try:
        while True:
            yield _evento({"line": next(gen)})
    except StopIteration as stop:
        code = stop.value if isinstance(stop.value, int) else 0
    except Exception as e:  # el registro debe mostrar el fallo, no cortar el stream
        yield _evento({"line": f"❌ Error: {e}"})
    yield _evento({"done": True, "code": code})


def _sse(gen):
    """
    Respuesta SSE con el candado de operación. Si ya hay otra corriendo,
    responde 409. El candado se suelta cuando el stream termina o el navegador
    lo corta (botón Detener).
    """
    if not _operacion.acquire(blocking=False):
        gen.close()
        return error("OCUPADO", "Ya hay una operación en curso; espera a que termine o detenla", 409)

    soltado = threading.Event()

    def soltar():
        # Se llama desde el fin del stream y desde el cierre de la respuesta:
        # el candado se suelta una sola vez aunque el stream nunca haya empezado
        if not soltado.is_set():
            soltado.set()
            gen.close()
            _operacion.release()

    def con_candado():
        try:
            yield from _sse_generador(gen)
        finally:
            soltar()

    resp = Response(stream_with_context(con_candado()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    resp.call_on_close(soltar)
    return resp


def _proceso(modulo: str, env: dict, confirmar: bool):
    """Corre una herramienta de consola y hace yield de su salida. Devuelve su código."""
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", modulo],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if confirmar else subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            cwd=str(BASE_DIR), env=env,
            start_new_session=True,  # grupo propio: Detener termina también a sus hijos
        )
    except OSError as e:
        yield f"❌ Error al iniciar el script: {e}"
        return 1
    if confirmar:
        proc.stdin.write("si\n")
        proc.stdin.close()
    try:
        for line in proc.stdout:
            yield line.rstrip()
    finally:
        if proc.poll() is None:  # el usuario detuvo la operación
            _terminar(proc)
        proc.stdout.close()
    return proc.wait()


def _terminar(proc: subprocess.Popen) -> None:
    """Termina el proceso y sus hijos (tiddl, ffmpeg); si no responde en 10 s, los mata."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    except ProcessLookupError:
        pass


# ── Páginas y estado ──────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/check-tiddl")
def check_tiddl():
    from core.descargar import verificar_tiddl

    ok, msg = verificar_tiddl()
    return jsonify({"ok": ok, "message": msg})


@app.get("/check-hires")
def check_hires():
    ok = sesion.sesion() is not None
    return jsonify({"ok": ok, "message": "Sesión de Tidal activa" if ok
                    else f"Ejecuta: {sesion.COMANDO_LOGIN}"})


@app.get("/library-stats")
def library_stats():
    from core.biblioteca import estadisticas

    return jsonify(estadisticas(_base(request.args.get("output_dir"))))


@app.get("/check-phone")
def check_phone():
    from core.telefono import estado

    if not _hay("adb"):
        return jsonify({"ok": False, "message": "sin adb", "hint": "Instala adb (android-tools)"})
    info = estado(_base(request.args.get("output_dir")))
    if not info["ok"]:
        return jsonify({"ok": False, "message": "sin conectar",
                        "hint": "Conecta el teléfono con la depuración USB activa y toca para volver a comprobar"})
    return jsonify({"ok": True, "message": info["modelo"],
                    "pending": info["pendientes"], "deleted": info["borrados"]})


@app.get("/playlists")
def playlists():
    from core.playlists import listar_playlists

    lista = listar_playlists()
    if lista is None:
        return error("SIN_SESION", str(sesion.SinSesion()), 401)
    return jsonify({"playlists": lista})


# ── Descargar: vista previa y descarga de cualquier link o de My Tracks ──────

def _recurso(texto: str | None, mytracks: bool):
    """Recurso de Tidal (con caché de 5 min) o una respuesta de error."""
    from core import recursos

    try:
        clave = "mytracks" if mytracks else str(interpretar(texto or ""))
    except EnlaceInvalido as e:
        return None, error("ENLACE_INVALIDO", str(e), 400)

    with _cache_lock:
        guardado = _cache_recursos.get(clave)
    if guardado and time.monotonic() - guardado[0] < _CACHE_SEGUNDOS:
        return guardado[1], None

    s = sesion.sesion()
    if s is None:
        return None, error("SIN_SESION", str(sesion.SinSesion()), 401)
    try:
        recurso = recursos.mis_tracks(s) if mytracks else recursos.resolver(s, interpretar(texto))
    except recursos.NoEncontrado as e:
        return None, error("NO_ENCONTRADO", str(e), 404)
    except Exception as e:  # red caída o respuesta rara de Tidal
        return None, error("ERROR_TIDAL", f"Tidal no respondió: {e}", 502)
    ahora = time.monotonic()
    with _cache_lock:
        for vieja in [k for k, (t, _) in _cache_recursos.items() if ahora - t >= _CACHE_SEGUNDOS]:
            del _cache_recursos[vieja]
        _cache_recursos[clave] = (ahora, recurso)
    return recurso, None


@app.post("/api/vista-previa")
def vista_previa():
    from core import recursos

    datos = _datos()
    recurso, err = _recurso(_texto(datos, "texto"), bool(datos.get("mytracks")))
    if err:
        return err
    return jsonify(recursos.vista_previa(recurso, _base(_texto(datos, "output_dir"))))


@app.post("/api/canciones")
def canciones():
    """Todas las canciones del recurso con su estado, para la ventana de selección."""
    from core import recursos

    datos = _datos()
    recurso, err = _recurso(_texto(datos, "texto"), bool(datos.get("mytracks")))
    if err:
        return err
    base = _base(_texto(datos, "output_dir"))
    return jsonify({**recursos.vista_previa(recurso, base), "canciones": recursos.canciones(recurso, base)})


@app.post("/run/descargar")
def run_descargar():
    from core import recursos

    datos = _datos()
    recurso, err = _recurso(_texto(datos, "texto"), bool(datos.get("mytracks")))
    if err:
        return err

    ids = datos.get("ids")
    if ids is not None:
        if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
            return error("SELECCION_INVALIDA", "Elige al menos una canción", 400)
        if set(ids) - {p.id for p in recurso.pistas}:
            return error("SELECCION_INVALIDA", f"Hay canciones que no son de «{recurso.nombre}»", 400)
    elif recurso.requiere_confirmar and datos.get("confirmado") is not True:
        return error("CONFIRMAR", f"Confirma antes de bajar {len(recurso.pistas)} canciones", 409)
    return _sse(recursos.descargar(recurso, _base(_texto(datos, "output_dir")), ids))


# ── Otras operaciones ─────────────────────────────────────────────────────────

@app.post("/run/hires")
def run_hires():
    from core.hires import mejorar

    return _sse(mejorar(_base(_texto(_datos(), "output_dir"))))


@app.post("/run/phone-sync")
def run_phone_sync():
    from core.telefono import DESTINO, enviar

    datos = _datos()
    return _sse(enviar(_base(_texto(datos, "output_dir")), _texto(datos, "destino").strip() or DESTINO,
                       datos.get("simular") is True))


@app.post("/run/<script>")
def run_script(script):
    if script not in SCRIPTS:
        return error("NO_EXISTE", "Herramienta no válida", 404)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    music_dir = _texto(_datos(), "music_dir").strip()
    if music_dir:
        env["TIDAL_MUSIC_DIR"] = music_dir
    return _sse(_proceso(SCRIPTS[script], env, script in AUTO_CONFIRM))


@app.post("/pick-folder")
def pick_folder():
    """Abre el selector de carpetas del sistema (zenity en GNOME, kdialog en KDE)."""
    titulo = "Seleccionar carpeta de música"
    comandos = [
        ["zenity", "--file-selection", "--directory", f"--title={titulo}"],
        ["kdialog", "--getexistingdirectory", str(Path.home()), "--title", titulo],
    ]
    for cmd in comandos:
        if not _hay(cmd[0]):
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            return jsonify({"path": ""})
        return jsonify({"path": r.stdout.strip() if r.returncode == 0 else ""})
    return error("SIN_SELECTOR", "Instala zenity para elegir carpetas", 501)


@app.post("/shutdown")
def shutdown():
    """Cierra el servidor después de responder."""
    def parar():
        time.sleep(0.3)  # margen para que el navegador reciba la respuesta
        os._exit(0)

    threading.Thread(target=parar, daemon=True).start()
    return jsonify({"ok": True})


if __name__ == "__main__":
    import webbrowser

    url = f"http://localhost:{PUERTO}"
    print("=" * 50)
    print("  Tidal Library Tools — Interfaz Web")
    print("=" * 50)
    print(f"\n  Abre tu navegador en:  {url}\n")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", debug=False, port=PUERTO, threaded=True)
