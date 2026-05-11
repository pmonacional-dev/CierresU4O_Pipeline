# export_vista.py
import sys
sys.dont_write_bytecode = True
import os
from pathlib import Path
import warnings
import pandas as pd
from openpyxl import Workbook  # asegura motor openpyxl
from conexionSQL import get_connection  
from rutas import get_paths  # <- nuevo
from typing import Optional  # si no lo tienes



# Silenciar warning de pandas cuando usa pyodbc "crudo"
warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy",
    category=UserWarning
)

# ========= Config de la vista (SQL) =========
VIEW_SCHEMA = "dbo"
VIEW_NAME   = "Tableau_WinRoom_ImagenFunnel_PBI"

# ========= Carpetas / archivos =========

# 1) Salida del Excel de la vista (fuente para procesamiento.py)
VISTA_XLSX      = f"{VIEW_NAME}.xlsx"

# 2) Nombre del modelo que genera procesamiento.py
MODELO_FILENAME = "modeloDatos.xlsx"


def export_view_to_excel(schema: str, view: str, out_path: str, sheet_name: str):
    Path(os.path.dirname(out_path)).mkdir(parents=True, exist_ok=True)

    print("Conectando al servidor...")
    with get_connection() as cn:
        query = f"SELECT * FROM [{schema}].[{view}]"
        df = pd.read_sql(query, cn)

    # Sobrescribe si existe
    if os.path.exists(out_path):
        os.remove(out_path)

    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)

    print(f"Vista exportada: {len(df):,} filas")
    print(f"Guardado en: {out_path}")

def copiar_a_onedrive(src: str, dst: str):
    # Intenta usar copy_with_retries del propio procesamiento.py; si no existe, usa shutil.copy2
    try:
        from procesamiento import copy_with_retries
        copy_with_retries(src, dst)
        print("Copiado a OneDrive (con reintentos)")
        
    except Exception:
        import shutil
        Path(os.path.dirname(dst)).mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print("✅ Copiado a OneDrive")


def generar_hu3_hu4(BASE_DIR: str, MODELO_LOCAL: str):
    """
    Corre las salidas de h3h4.py sobre el modelo ya generado.
    """
    try:
        from h3h4 import (
            configure_paths,               # <- NUEVO
            generar_categoria_asesores,
            generar_ventas_asesores_region,
            generar_ventas_asesores_general,
            generar_ventas_asesores_nacional,
            generar_actualizacion,
        )
    except ImportError as e:
        raise ImportError(
            "No pude importar h3h4.py. Verifica que el archivo está en la misma carpeta "
            "y que el nombre del módulo es correcto."
        ) from e

    # Verificaciones mínimas
    vista_xlsx = os.path.join(BASE_DIR, "Tableau_WinRoom_ImagenFunnel_PBI.xlsx")
    if not os.path.exists(vista_xlsx):
        raise FileNotFoundError(
            f"No encuentro la vista exportada para HU3/HU4:\n  {vista_xlsx}\n"
            "Asegúrate que export_view_to_excel corrió bien."
        )
    if not os.path.exists(MODELO_LOCAL):
        raise FileNotFoundError(
            f"No encuentro el modelo para HU3/HU4:\n  {MODELO_LOCAL}\n"
            "Asegúrate que procesamiento.py generó el archivo."
        )

    # Apuntar h3h4 al BASE_DIR correcto (modeloDatos.xlsx y WinRoom en esa carpeta)
    configure_paths(BASE_DIR)  # <- NUEVO

    # Ejecutar en orden
    print("\nGenerando tablas HU3/HU4...")
    generar_categoria_asesores()          # CategoriaAsesores
    generar_ventas_asesores_region()      # VentasAsesoresRegion
    generar_ventas_asesores_general()     # VentasAsesoresGeneral
    generar_ventas_asesores_nacional()    # VentasAsesoresNacional
    generar_actualizacion()
    print("✅ HU3/HU4 listas en modeloDatos.xlsx")


def main(origen: Optional[str] = None):
    # Rutas centralizadas por origen/usuario
    print("ORIGEN:   ", origen)
    BASE_DIR, ONEDRIVE_DIR = get_paths(origen)
    VISTA_PATH   = os.path.join(BASE_DIR, "Tableau_WinRoom_ImagenFunnel_PBI.xlsx")
    VISTA_SHEET  = "Result 1"
    MODELO_LOCAL = os.path.join(BASE_DIR, "modeloDatos.xlsx")
    MODELO_OD    = os.path.join(ONEDRIVE_DIR, "modeloDatos.xlsx")

    # 1) Exportar la vista WinRoom al BASE_DIR
    export_view_to_excel(
        schema=VIEW_SCHEMA,
        view=VIEW_NAME,
        out_path=VISTA_PATH,
        sheet_name=VISTA_SHEET,
    )

    # 2) Generar modeloDatos.xlsx LOCAL (llamando al procesamiento)
    print("\nGenerando modeloDatos.xlsx...")
    from procesamiento import generar_modelodatos
    try:
        # Si ya adaptaste procesamiento.py a aceptar rutas:
        generar_modelodatos(base_dir=BASE_DIR, dst_path=MODELO_LOCAL, src_path=VISTA_PATH)
    except TypeError:
        # Si aún no lo adaptas, usa tu invocación anterior:
        generar_modelodatos()
    print(f"✅ Generado: {MODELO_LOCAL}")

    # 2.5) Generar HU3/HU4 (h3h4.py)
    generar_hu3_hu4(BASE_DIR, MODELO_LOCAL)

    # 3) Subir a OneDrive (desde aquí mismo)
    print("\n Subiendo modeloDatos.xlsx a OneDrive...")
    if os.path.abspath(MODELO_LOCAL) == os.path.abspath(MODELO_OD):
        print("El archivo ya está en OneDrive; no es necesario copiar.")
    else:
        copiar_a_onedrive(MODELO_LOCAL, MODELO_OD)

if __name__ == "__main__":
    import argparse, os
    parser = argparse.ArgumentParser(description="Exporta WinRoom, construye modelo y HU3/HU4.")
    parser.add_argument(
        "--origen",
        choices=["Andrea", "Antonio", "Erik"],
        default=os.getenv("U4O_ORIGEN"),  # si viene del entorno; si no, usa default en rutas.py
        help="Origen de rutas; si se omite, se usa el DEFAULT de rutas.py",
    )
    args = parser.parse_args()
    main(args.origen)
