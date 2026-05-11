import configparser
import os
from simple_salesforce import Salesforce, SalesforceAuthenticationFailed

def connect_to_salesforce():
    config = configparser.ConfigParser()

    # Ruta absoluta al ini (en la MISMA carpeta que Conexion_SalesForce.py)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.ini")  # <-- si tu archivo se llama distinto, cámbialo aquí

    print("CWD:", os.getcwd())
    print("Intentando leer:", config_path)

    leidos = config.read(config_path, encoding="utf-8")
    print("Leyó:", leidos)
    print("Secciones:", config.sections())

    # Validación clara (para que no truene con KeyError sin contexto)
    if "salesforce" not in config:
        raise KeyError(f"No existe la sección [salesforce] en {config_path}")

    uname = config["salesforce"].get("username")
    pwd = config["salesforce"].get("password")
    token = config["salesforce"].get("security_token")

    if not uname or not pwd or not token:
        raise KeyError(f"Faltan keys en [salesforce] (username/password/security_token) en {config_path}")

    try:
        sf = Salesforce(username=uname, password=pwd, security_token=token)
        print("Conexión a Salesforce establecida exitosamente.")
        return sf

    except SalesforceAuthenticationFailed as e:
        print("La autenticación con Salesforce falló:", e)
        return None

    except Exception as e:
        print("Ocurrió un error desconocido al intentar conectar con Salesforce:", e)
        return None
