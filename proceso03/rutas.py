# rutas.py
import json, os, getpass

_DEFAULT_JSON = os.path.join(os.path.dirname(__file__), "rutas.json")

# <<< AQUÍ SE PONE AL USUARIO POR DEFAULT SOLO SE TIENE QUE CAMBIAR EL NOMBRE POR Antonio o por Erik>>>
DEFAULT_ORIGEN = os.getenv("U4O_ORIGEN", "Andrea") 

def _load_json(path=_DEFAULT_JSON):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_paths(origen: str | None = None, rutas_json: str | None = None):
    """
    Devuelve (BASE_DIR, ONEDRIVE_DIR).
    Orden de resolución:
      1) origen explícito (si está en data)
      2) DEFAULT_ORIGEN (si está en data)
      3) autodetección por usuario de Windows (getpass.getuser())
      4) error si nada coincide
    """
    data = _load_json(rutas_json or _DEFAULT_JSON)

    # 1) origen explícito
    if origen and origen in data:
        conf = data[origen]
        return conf["BASE_DIR"], conf["ONEDRIVE_DIR"]

    # 2) DEFAULT_ORIGEN (incluye posible U4O_ORIGEN desde el entorno)
    if DEFAULT_ORIGEN in data:
        conf = data[DEFAULT_ORIGEN]
        return conf["BASE_DIR"], conf["ONEDRIVE_DIR"]

    # 3) Autodetección por usuario de Windows
    user = getpass.getuser()
    for nombre, conf in data.items():
        if user.lower() in conf["BASE_DIR"].lower():
            return conf["BASE_DIR"], conf["ONEDRIVE_DIR"]

    # 4) Nada coincidió
    raise KeyError(
        f"No encontré configuración de rutas para origen='{origen}' "
        f"ni DEFAULT_ORIGEN='{DEFAULT_ORIGEN}' ni usuario Windows='{user}'. "
        f"Edita rutas.json o ajusta DEFAULT_ORIGEN. "
        f"Orígenes válidos: {list(data.keys())}"
    )
