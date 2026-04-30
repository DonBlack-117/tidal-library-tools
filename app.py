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


@app.route("/run/download", methods=["POST"])
def run_download():
    from core.descargar import descargar_recurso

    data = request.get_json(silent=True) or {}
    tidal_url = data.get("tidal_url", "").strip()
    output_dir = data.get("output_dir", "").strip()
    quality = data.get("quality", "AUTO").strip()
    cover = bool(data.get("cover", True))

    if not tidal_url:
        return jsonify({"error": "URL requerida"}), 400

    def generate():
        for line in descargar_recurso(tidal_url, output_dir, quality, cover):
            yield f"data: {json.dumps({'line': line})}\n\n"
        yield f"data: {json.dumps({'done': True, 'code': 0})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/check-tiddl", methods=["GET"])
def check_tiddl():
    from core.descargar import verificar_tiddl

    ok, msg = verificar_tiddl()
    return jsonify({"ok": ok, "message": msg})


@app.route("/pick-folder", methods=["POST"])
def pick_folder():
    """
    Abre el selector de carpetas nativo del SO usando tkinter.
    Devuelve la ruta elegida o una cadena vacía si el usuario cancela.
    tkinter corre en un hilo aparte para no bloquear Flask.
    """
    import tkinter as tk
    from tkinter import filedialog

    selected = {"path": ""}

    def open_dialog():
        root = tk.Tk()
        root.withdraw()  # oculta la ventana principal de tkinter
        root.wm_attributes("-topmost", True)  # el diálogo aparece al frente
        path = filedialog.askdirectory(title="Seleccionar carpeta de música")
        root.destroy()
        selected["path"] = path or ""

    t = threading.Thread(target=open_dialog)
    t.start()
    t.join()  # espera a que el usuario cierre el diálogo antes de responder

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
