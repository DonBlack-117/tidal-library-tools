#!/usr/bin/env python3
"""
Servidor web local para Tidal Library Tools.
Corre en http://localhost:5000

Uso:
  pip install flask
  python app.py
"""

import os
import sys
import json
import shutil
import threading
import subprocess
from pathlib import Path
from flask import (
    Flask,
    render_template,
    request,
    Response,
    stream_with_context,
    jsonify,
)

app = Flask(__name__)
BASE_DIR = Path(__file__).parent

SCRIPTS = {
    "sync": "core/sincronizar.py",
    "quality": "core/mejorar_calidad.py",
    "dupes": "core/limpiar_duplicados.py",
}

# Estos scripts piden confirmación "si" en mitad de la ejecución.
# Al hacer clic en Ejecutar el usuario ya confirmó, así que lo
# enviamos automáticamente por stdin.
AUTO_CONFIRM = {"quality", "dupes"}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run/<script>", methods=["POST"])
def run_script(script):
    if script not in SCRIPTS:
        return {"error": "Script no válido"}, 400

    config = request.get_json(silent=True) or {}
    music_dir = config.get("music_dir", "")

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if music_dir:
        env["TIDAL_MUSIC_DIR"] = music_dir

    def generate():
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", SCRIPTS[script]],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if script in AUTO_CONFIRM else None,
                text=True,
                bufsize=1,
                cwd=str(BASE_DIR),
                env=env,
            )
        except Exception as e:
            yield f"data: {json.dumps({'line': f'❌ Error al iniciar el script: {e}'})}\n\n"
            yield f"data: {json.dumps({'done': True, 'code': 1})}\n\n"
            return

        if script in AUTO_CONFIRM:
            try:
                proc.stdin.write("si\n")
                proc.stdin.flush()
                proc.stdin.close()
            except Exception:
                pass

        for line in proc.stdout:
            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"

        proc.wait()
        yield f"data: {json.dumps({'done': True, 'code': proc.returncode})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse_generador(gen):
    """Convierte un generador de líneas en eventos SSE y envía el returncode real."""
    code = 1
    try:
        while True:
            line = next(gen)
            yield f"data: {json.dumps({'line': line})}\n\n"
    except StopIteration as stop:
        code = stop.value if isinstance(stop.value, int) else 0
    except Exception as e:
        yield f"data: {json.dumps({'line': f'❌ Error: {e}'})}\n\n"
    yield f"data: {json.dumps({'done': True, 'code': code})}\n\n"


def _sse_response(gen):
    return Response(
        stream_with_context(_sse_generador(gen)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/run/download", methods=["POST"])
def run_download():
    from core.descargar import descargar_recurso

    data = request.get_json(silent=True) or {}
    tidal_url = data.get("tidal_url", "").strip()
    output_dir = data.get("output_dir", "").strip()

    if not tidal_url:
        return jsonify({"error": "URL requerida"}), 400

    return _sse_response(descargar_recurso(tidal_url, output_dir))


@app.route("/run/download-mytracks", methods=["POST"])
def run_download_mytracks():
    from core.descargar import descargar_mis_tracks

    data = request.get_json(silent=True) or {}
    output_dir = data.get("output_dir", "").strip()

    return _sse_response(descargar_mis_tracks(output_dir))


@app.route("/playlists", methods=["GET"])
def playlists():
    from core.playlists import listar_playlists

    try:
        lista = listar_playlists()
    except Exception as e:
        return jsonify({"ok": False, "message": str(e), "playlists": []})
    if lista is None:
        return jsonify({"ok": False, "message": "Falta la sesión Hi-Res (PKCE)", "playlists": []})
    return jsonify({"ok": True, "playlists": lista})


@app.route("/run/download-playlist", methods=["POST"])
def run_download_playlist():
    from core.playlists import descargar_playlist

    data = request.get_json(silent=True) or {}
    playlist = data.get("playlist", "").strip()
    if not playlist:
        return jsonify({"error": "Playlist requerida"}), 400
    return _sse_response(descargar_playlist(playlist, data.get("output_dir", "").strip()))


@app.route("/check-hires", methods=["GET"])
def check_hires():
    from core.hires import sesion

    try:
        ok = sesion() is not None
    except Exception:
        ok = False
    return jsonify({"ok": ok,
                    "message": "Sesión Hi-Res activa" if ok
                    else "Ejecuta: .venv/bin/python -m core.hires login"})


@app.route("/run/hires", methods=["POST"])
def run_hires():
    from core.descargar import DEFAULT_OUTPUT_DIR
    from core.hires import mejorar

    data = request.get_json(silent=True) or {}
    base = Path(data.get("output_dir", "").strip() or DEFAULT_OUTPUT_DIR).expanduser()
    return _sse_response(mejorar(base))


@app.route("/check-phone", methods=["GET"])
def check_phone():
    from core.descargar import DEFAULT_OUTPUT_DIR
    from core.telefono import estado

    if not shutil.which("adb"):
        return jsonify({"ok": False, "message": "sin adb", "hint": "Instala adb (android-tools)"})
    base = Path(request.args.get("output_dir", "").strip() or DEFAULT_OUTPUT_DIR).expanduser()
    info = estado(base)
    if not info["ok"]:
        return jsonify({"ok": False, "message": "sin conectar",
                        "hint": "Conecta el teléfono con la depuración USB activa y toca para volver a comprobar"})
    return jsonify({"ok": True, "message": info["modelo"],
                    "pending": info["pendientes"], "deleted": info["borrados"]})


@app.route("/library-stats", methods=["GET"])
def library_stats():
    from core.biblioteca import estadisticas
    from core.descargar import DEFAULT_OUTPUT_DIR

    base = Path(request.args.get("output_dir", "").strip() or DEFAULT_OUTPUT_DIR).expanduser()
    return jsonify(estadisticas(base))


@app.route("/run/phone-sync", methods=["POST"])
def run_phone_sync():
    from core.descargar import DEFAULT_OUTPUT_DIR
    from core.telefono import DESTINO, enviar

    data = request.get_json(silent=True) or {}
    base = Path(data.get("output_dir", "").strip() or DEFAULT_OUTPUT_DIR).expanduser()
    return _sse_response(enviar(base, data.get("destino", "").strip() or DESTINO,
                                bool(data.get("simular"))))


@app.route("/check-tiddl", methods=["GET"])
def check_tiddl():
    from core.descargar import verificar_tiddl

    ok, msg = verificar_tiddl()
    return jsonify({"ok": ok, "message": msg})


@app.route("/pick-folder", methods=["POST"])
def pick_folder():
    """
    Abre el selector de carpetas nativo del SO.
    En Linux prefiere zenity (GTK, compatible con Wayland/GNOME en Fedora)
    o kdialog (KDE) antes de intentar tkinter.
    """
    selected = {"path": ""}

    # ── zenity (GNOME / Fedora) ──────────────────────────────────────────────
    if shutil.which("zenity"):
        try:
            result = subprocess.run(
                ["zenity", "--file-selection", "--directory",
                 "--title=Seleccionar carpeta de música"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                selected["path"] = result.stdout.strip()
            return {"path": selected["path"]}
        except Exception:
            pass

    # ── kdialog (KDE) ────────────────────────────────────────────────────────
    if shutil.which("kdialog"):
        try:
            result = subprocess.run(
                ["kdialog", "--getexistingdirectory",
                 str(Path.home()), "--title", "Seleccionar carpeta de música"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                selected["path"] = result.stdout.strip()
            return {"path": selected["path"]}
        except Exception:
            pass

    # ── tkinter (fallback universal) ─────────────────────────────────────────
    try:
        import tkinter as tk
        from tkinter import filedialog

        def open_dialog():
            root = tk.Tk()
            root.withdraw()
            try:
                root.wm_attributes("-topmost", True)
            except Exception:
                pass
            path = filedialog.askdirectory(title="Seleccionar carpeta de música")
            root.destroy()
            selected["path"] = path or ""

        t = threading.Thread(target=open_dialog)
        t.start()
        t.join()
    except Exception:
        pass

    return {"path": selected["path"]}


@app.route("/shutdown", methods=["POST"])
def shutdown():
    """
    Cierra el servidor Flask de forma limpia.
    Envía la respuesta primero y luego termina el proceso con un pequeño delay.
    """

    def stop():
        import time

        time.sleep(0.3)  # margen para que el navegador reciba la respuesta
        os._exit(0)

    threading.Thread(target=stop, daemon=True).start()
    return {"ok": True}


if __name__ == "__main__":
    import webbrowser

    print("=" * 50)
    print("  Tidal Library Tools — Interfaz Web")
    print("=" * 50)
    print("\n  Abre tu navegador en:  http://localhost:5000\n")
    threading.Timer(0.8, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(debug=False, port=5000, threaded=True)
