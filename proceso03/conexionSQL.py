# db_connection.py
import sys
sys.dont_write_bytecode = True

import pyodbc

# CONFIGURACIÓN DE LA CONEXIÓN

SQLSERVER_HOST = "www.edatasoluciones.com"   
INSTANCE_NAME  = ""                           
SQLSERVER_PORT = "8081"                      

DATABASE_NAME  = "Edata_Qlik"
SQLSERVER_USER = "tableauviewer"
SQLSERVER_PASSWORD = "aries724$"
USE_TRUSTED_CONNECTION = False              

POSSIBLE_DRIVERS = [
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server"
]

def _pick_driver():
    installed = [d for d in pyodbc.drivers()]
    for d in POSSIBLE_DRIVERS:
        if d in installed:
            return d, installed
    raise RuntimeError("No se encontró un driver ODBC para SQL Server.")

def _build_server_segment():
    if INSTANCE_NAME:
        return f"{SQLSERVER_HOST}\\{INSTANCE_NAME}"
    else:
        return f"{SQLSERVER_HOST},{SQLSERVER_PORT}"

def build_connection_string():
    """
    Devuelve la cadena de conexión lista para usar con pyodbc.connect().
    También imprime el driver elegido y oculta la contraseña en la salida.
    """
    driver, installed = _pick_driver()
    server_seg = _build_server_segment()

    print("Drivers ODBC instalados:", installed)
    print("Driver seleccionado:", driver)

    base_common = f"DRIVER={{{driver}}};SERVER={server_seg};DATABASE={DATABASE_NAME};Timeout=30;"
    modern = driver.startswith("ODBC Driver")
    if modern:
        base_common += "Encrypt=yes;TrustServerCertificate=yes;"

    if USE_TRUSTED_CONNECTION:
        conn = base_common + "Trusted_Connection=Yes;"
    else:
        conn = base_common + f"UID={SQLSERVER_USER};PWD={SQLSERVER_PASSWORD};"

    print("Cadena (pwd oculto):", conn.replace(SQLSERVER_PASSWORD, "*****"))
    return conn

def get_connection():
    """Abre y devuelve una conexión pyodbc lista para usarse (context manager compatible)."""
    conn_str = build_connection_string()
    return pyodbc.connect(conn_str)
