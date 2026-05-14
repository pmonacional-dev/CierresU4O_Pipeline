# -*- coding: utf-8 -*-
"""
Lanzador de flujos nocturnos.
- Permite elegir origen por CLI: --origen Andrea|Antonio|Erik
- Si no se especifica, deja que import_export.main() use el default definido en rutas.py
"""
from import_export import main as main_export
import os
import argparse
import sys, os, platform
import pandas as pd
import pyodbc


def ejecutar_flujos(origen: str | None = None):
    if os.getenv("U4O_DRY_RUN", "0") == "1":
        import dryrun  # noqa: F401 — activa el modo prueba antes de cualquier conexión
    print("Iniciando ejecución de flujos...")

    print("1) import_export")
    main_export(origen)  # None -> usa DEFAULT_ORIGEN/U4O_ORIGEN dentro de rutas.py

    print("Ejecución completa.")

if __name__ == "__main__":
    import os
    origen = os.getenv("U4O_ORIGEN", "Erik")  # Erik, Andrea o Antonio

    print("Python exe:", sys.executable)
    print("Python version:", sys.version)
    print("Platform:", platform.platform())
    print("Arquitectura:", platform.architecture())
    print("CWD:", os.getcwd())
    print("pandas:", pd.__version__)
    print("pyodbc:", pyodbc.version)
    print("ODBC drivers:", pyodbc.drivers())
        
    """
    parser = argparse.ArgumentParser(description="Ejecutor de cierres U4O")
    parser.add_argument(
        "--origen",
        choices=["Andrea", "Antonio", "Erik"],
        default=os.getenv("U4O_ORIGEN"),  # si viene del entorno, se usa; si no, queda None
        help="Origen de rutas (si se omite, se toma el default de rutas.py)"
    )
    args = parser.parse_args()
    """

    # Pasamos None si no se especificó; main() resolverá el default
    #ejecutar_flujos(args.origen)
    ejecutar_flujos(origen)