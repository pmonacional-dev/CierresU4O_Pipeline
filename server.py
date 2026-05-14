"""
Servidor web para el orquestador CierresU4O Pipeline.
Sirve el frontend HTML y transmite el progreso del pipeline via SSE.

Uso:
    pip install flask
    python server.py
    Abrir http://localhost:5000 en el navegador
"""
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_file

BASE = Path(__file__).parent
app = Flask(__name__)

# job_id -> {"queue": Queue, "proc": Popen | None}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Rutas HTTP
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_file(BASE / "frontend.html")


@app.route("/iniciar", methods=["POST"])
def iniciar():
    data = request.get_json(force=True)
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()

    with _jobs_lock:
        _jobs[job_id] = {"queue": q, "proc": None}

    threading.Thread(target=_run_pipeline, args=(job_id, q, data), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/stream/<job_id>")
def stream(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return Response("Job no encontrado", status=404)

    def generate():
        q = job["queue"]
        while True:
            try:
                msg = q.get(timeout=30)
                yield f"data: {msg}\n\n"
                parsed = json.loads(msg)
                if parsed.get("type") == "done":
                    break
            except queue.Empty:
                yield 'data: {"type":"heartbeat"}\n\n'

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Ejecución del pipeline en hilo separado
# ---------------------------------------------------------------------------

_SCRIPTS = {
    "proceso01": BASE / "proceso01" / "CierresU4O_Proceso01.py",
    "proceso02": BASE / "proceso02" / "CierresU4O_Proceso02.py",
    "proceso03": BASE / "proceso03" / "CierresU4O_Proceso03.py",
}
_NOMBRES = {
    "proceso01": "Proceso 01 — Extracción y Centralización ETL",
    "proceso02": "Proceso 02 — Inserción, Actualización y Exportación CRM",
    "proceso03": "Proceso 03 — Exportación Formato Universal",
}


def _emit(q: queue.Queue, msg: dict) -> None:
    q.put(json.dumps(msg, ensure_ascii=False))


def _run_pipeline(job_id: str, q: queue.Queue, data: dict) -> None:
    dry_run = "1" if data.get("dry_run") else "0"

    # Agregar el root del proyecto al PYTHONPATH para que 'import dryrun' funcione
    existing_pp = os.environ.get("PYTHONPATH", "")
    pythonpath = str(BASE) + (os.pathsep + existing_pp if existing_pp else "")

    env = {
        **os.environ,
        "U4O_ORIGEN":       data.get("origen", "Erik"),
        "U4O_PERIODO":      data.get("periodo", "Semanal"),
        "U4O_FECHACAMBIO":  data.get("fechacambio", ""),
        "U4O_ANIO_META":    data.get("anio_meta", "2025-2026"),
        "U4O_AUTO_CONFIRM": "1",
        "U4O_DRY_RUN":      dry_run,
        "PYTHONPATH":       pythonpath,
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }

    procesos = data.get("procesos", ["proceso01", "proceso02", "proceso03"])
    inicio_total = datetime.now()

    for key in procesos:
        script = _SCRIPTS[key]
        nombre = _NOMBRES[key]
        _emit(q, {"type": "proceso_start", "proceso": key, "nombre": nombre})

        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", script.name],
                cwd=str(script.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            with _jobs_lock:
                _jobs[job_id]["proc"] = proc

            for line in proc.stdout:
                _emit(q, {"type": "log", "proceso": key, "text": line.rstrip()})

            proc.wait()
            status = "ok" if proc.returncode == 0 else "error"
            _emit(q, {"type": "proceso_end", "proceso": key, "status": status, "returncode": proc.returncode})

            if proc.returncode != 0:
                _emit(q, {"type": "done", "status": "error"})
                return

        except Exception as exc:
            _emit(q, {"type": "proceso_end", "proceso": key, "status": "error", "error": str(exc)})
            _emit(q, {"type": "done", "status": "error"})
            return

    duracion = str(datetime.now() - inicio_total).split(".")[0]
    _emit(q, {"type": "done", "status": "ok", "duracion": duracion})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 55)
    print("  CierresU4O Pipeline — Servidor Web")
    print(f"  Abrir en el navegador: http://localhost:5000")
    print("=" * 55)
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
