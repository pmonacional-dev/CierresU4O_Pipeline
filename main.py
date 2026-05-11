"""
Orquestador principal — Cierres U4O
Ejecuta los tres procesos en secuencia:
    Proceso 01 (Erik)    → extraccion y centralizacion ETL
    Proceso 02 (Antonio) → insercion, actualizacion y exportacion CRM
    Proceso 03 (Andrea)  → exportacion formato universal
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent

PROCESOS = [
    (BASE / "proceso01" / "CierresU4O_Proceso01.py", "Proceso 01 — Erik"),
    (BASE / "proceso02" / "CierresU4O_Proceso02.py", "Proceso 02 — Antonio"),
    (BASE / "proceso03" / "CierresU4O_Proceso03.py", "Proceso 03 — Andrea"),
]


def run_proceso(script: Path, nombre: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {nombre}")
    print(f"  Inicio: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'=' * 60}")
    subprocess.run(
        [sys.executable, script.name],
        cwd=str(script.parent),
        check=True,
    )
    print(f"  Fin:    {datetime.now():%Y-%m-%d %H:%M:%S}")


if __name__ == "__main__":
    inicio = datetime.now()
    print(f"\nCierres U4O — inicio: {inicio:%Y-%m-%d %H:%M:%S}")

    for script, nombre in PROCESOS:
        run_proceso(script, nombre)

    fin = datetime.now()
    duracion = fin - inicio
    print(f"\n{'=' * 60}")
    print(f"  Cierres U4O completados")
    print(f"  Fin: {fin:%Y-%m-%d %H:%M:%S}  |  Duracion: {duracion}")
    print(f"{'=' * 60}\n")
