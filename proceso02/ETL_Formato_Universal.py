# -*- coding: utf-8 -*-
"""
Proyecto: Formato Universal (P-Hub)
ETL para poblar Edata_Qlik.dbo.PHub_Formato_Universal_Tabla

Fixes incluidos:
- Elimina NaN/NaT en columnas varchar (Campus venía como nan float)
- Fecha_actualizacion se fuerza a datetime.datetime (Python), NO pandas.Timestamp
- Sanitizado de tipos y truncado por longitud de columna
- Insert robusto evitando cacheo/bindings raros del driver

Requisitos:
- pandas
- tu módulo Conexion_SQL con crear_conexion_sql(name)
"""

import re
import math
import unicodedata
import warnings
from datetime import datetime, date

import pandas as pd

from Conexion_SQL import crear_conexion_sql


# =============================================================================
# Utilidades generales
# =============================================================================
def _strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def norm_for_match(val) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    s = _strip_accents(s)
    s = re.sub(r"[;,:()\[\]{}'\"“”‘’´`|/\\]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def best_match_by_earliest_occurrence(full_text, candidates):
    full_n = norm_for_match(full_text)
    if not full_n:
        return None

    best = None
    best_pos = None
    best_len = None

    for cand in candidates:
        cand_n = norm_for_match(cand)
        if not cand_n:
            continue
        pos = full_n.find(cand_n)
        if pos == -1:
            continue

        if (best is None) or (pos < best_pos) or (pos == best_pos and len(cand_n) > best_len):
            best = cand
            best_pos = pos
            best_len = len(cand_n)

    return best


def chunks(lst, n=900):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def read_sql_df(conn, query: str, params=None) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="pandas only supports SQLAlchemy connectable*",
            category=UserWarning
        )
        return pd.read_sql_query(query, conn, params=params)


def fetch_in_chunks(conn, base_query_with_placeholder: str, values: list, chunk_size: int = 900) -> pd.DataFrame:
    if not values:
        return pd.DataFrame()

    dfs = []
    for part in chunks(values, chunk_size):
        ph = ",".join(["?"] * len(part))
        q = base_query_with_placeholder.format(placeholders=ph)
        dfs.append(read_sql_df(conn, q, params=part))

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


# =============================================================================
# Diccionarios de transformación
# =============================================================================
CAMPUS_MAP = {
    "Campus Aguascalientes": "Aguascalientes - 086",
    "Campus Chiapas": "Chiapas - 022",
    "Campus Chihuahua": "Chihuahua - 007",
    "Campus Ciudad de México": "Ciudad de México - 032",
    "Campus Cd. Juárez": "Ciudad Juárez - 006",
    "Campus Colima": "Colima - 027",
    "Campus Cuernavaca": "Cuernavaca - 024",
    "Campus Cumbres": "Cumbres - 061",
    "Educación en Línea": "Educación en Línea - 087",
    "Campus Estado de México": "Estado de México - 023",
    "Campus Eugenio Garza Lagüera": "Eugenio Garza Lagüera - 059",
    "Campus Eugenio Garza Laguera": "Eugenio Garza Lagüera - 059",
    "Campus Eugenio Garza Sada": "Eugenio Garza Sada - 058",
    "Campus Guadalajara": "Guadalajara - 028",
    "Campus Hidalgo": "Hidalgo - 013",
    "Instituto para el Futuro de la Educación": "Instituto para el Futuro de la Educación - 085",
    "Campus Irapuato": "Irapuato - 014",
    "Campus Laguna": "Laguna - 008",
    "Campus León": "León - 015",
    "Campus Leon": "León - 015",
    "Campus Mixcoac": "Mixcoac - 072",
    "Campus Monterrey": "Monterrey - 002",
    "Campus Morelia": "Morelia - 045",
    "Campus Obregón": "Obregón - 026",
    "Campus Obregon": "Obregón - 026",
    "Campus Puebla": "Puebla - 046",
    "Campus Querétaro": "Querétaro - 016",
    "Campus Queretaro": "Querétaro - 016",
    "Rectoría Tec de Monterrey": "Rectoría Tec de Monterrey - 070",
    "Rectoria Tec de Monterrey": "Rectoría Tec de Monterrey - 070",
    "Campus Saltillo": "Saltillo - 009",
    "Campus San Luis Potosí": "San Luis Potosí - 017",
    "Campus San Luis Potosi": "San Luis Potosí - 017",
    "Campus San Pedro": "San Pedro - 075",
    "Campus Santa Catarina": "Santa Catarina - 060",
    "Campus Santa Fe": "Santa Fe - 090",
    "Sede Peru": "Sede Perú - 021",
    "Sede Perú": "Sede Perú - 021",
    "Campus Sinaloa": "Sinaloa - 030",
    "Campus Sonora Norte": "Sonora Norte - 031",
    "Campus Tampico": "Tampico - 010",
    "Campus Toluca": "Toluca - 018",
    "Campus Valle Alto": "Valle Alto - 062",
    "Campus Zacatecas": "Zacatecas - 011",
    "Campus Expedition": "Expedition - 004",
    "LATAM - Chile": "Rectoría Tec de Monterrey - 070",
    "LATAM - Colombia Bogotá": "Rectoría Tec de Monterrey - 070",
    "LATAM - Costa Rica": "Rectoría Tec de Monterrey - 070",
    "LATAM - Ecuador - Guayaquil": "Rectoría Tec de Monterrey - 070",
    "LATAM - Ecuador - Quito": "Rectoría Tec de Monterrey - 070",
    "LATAM - Panamá": "Rectoría Tec de Monterrey - 070",
    "LATAM - Perú": "Rectoría Tec de Monterrey - 070",
}
CAMPUS_MAP_N = {norm_for_match(k): v for k, v in CAMPUS_MAP.items()}

ESCUELA_CODE = {
    "Negocios": "Negocios - C",
    "Ingeniería y Ciencias": "Ingeniería y Ciencias - B",
    "Ingenieria y Ciencias": "Ingeniería y Ciencias - B",
    "Ciencias Sociales y Gobierno": "Ciencias Sociales y Gobierno - E",
    "Medicina y Ciencias de la Salud": "Medicina y Ciencias de la Salud - D",
    "Arquitectura y Diseño": "Arquitectura y Diseño - G",
    "Arquitectura y Diseno": "Arquitectura y Diseño - G",
    "Humanidades y Educación": "Humanidades y Educación - F",
    "Humanidades y Educacion": "Humanidades y Educación - F",
    "Multiescuela": "Multiescuela - I",
}
ESCUELA_CODE_N = {norm_for_match(k): v for k, v in ESCUELA_CODE.items()}

ESCUELA_CATEGORIAS_CANON = {
    norm_for_match("Negocios"): "Negocios",
    norm_for_match("Ingeniería y Ciencias"): "Ingeniería y Ciencias",
    norm_for_match("Ingenieria y Ciencias"): "Ingeniería y Ciencias",
    norm_for_match("Ciencias Sociales y Gobierno"): "Ciencias Sociales y Gobierno",
    norm_for_match("Medicina y Ciencias de la Salud"): "Medicina y Ciencias de la Salud",
    norm_for_match("Arquitectura y Diseño"): "Arquitectura y Diseño",
    norm_for_match("Arquitectura y Diseno"): "Arquitectura y Diseño",
    norm_for_match("Humanidades y Educación"): "Humanidades y Educación",
    norm_for_match("Humanidades y Educacion"): "Humanidades y Educación",
    norm_for_match("Multiescuela"): "Multiescuela",
}

TIPO_PROGRAMA_MAP = [
    ("Diplomado", "Diplomado", "1"),
    ("Seminario", "Seminario", "2"),
    ("Curso", "Curso", "3"),
    ("Certificado", "Certificado", "4"),
    ("Conferencia", "Conferencias o Simposium", "5"),
    ("Asesorías", "Asesorías", "6"),
    ("Asesorias", "Asesorías", "6"),
    ("Taller", "Taller", "7"),
    ("Idiomas", "Idiomas", "8"),
    ("Consultoría", "Consultoría", "9"),
    ("Consultoria", "Consultoría", "9"),
    ("Bootcamp", "Bootcamp", "0"),
    ("Mooc´s", "Mooc´s", "A"),
    ("Moocs", "Mooc´s", "A"),
    ("MicroMaster", "MicroMaster", "B"),
    ("Servicios Profesionales", "Servicios Profesionales", "C"),
    ("Certificado Alta Especialidad", "Certificado Alta Especialidad", "D"),
    ("Flexpath", "Flexpath", "E"),
    ("Certificación TLG", "Certificación TLG", "H"),
    ("Certificacion TLG", "Certificación TLG", "H"),
    ("Certificación", "Certificación", "F"),
    ("Certificacion", "Certificación", "F"),
    ("Microcertificado", "Microcertificado", "G"),
    ("Trayectoria", "Trayectoria", "I"),
    ("Competencia", "Competencia", "J"),
    ("Subcompetencia", "Subcompetencia", "K"),
    ("LAB", "LAB", "L"),
    ("Diagnóstico", "Diagnóstico", "M"),
    ("Diagnostico", "Diagnóstico", "M"),
    ("Mentoría", "Mentoría", "N"),
    ("Mentoria", "Mentoría", "N"),
    ("Coaching", "Coaching", "O"),
]
TIPO_CANDIDATES = [x[0] for x in TIPO_PROGRAMA_MAP]
TIPO_TO_OUT = {x[0]: f"{x[1]} {x[2]}" for x in TIPO_PROGRAMA_MAP}

AREA_MAP = {
    "Negocios": [
        ("Mercadotecnia", "Mercadotecnia", "A"),
        ("Finanzas y Contabilidad", "Finanzas y Contabilidad", "B"),
        ("Negocios Internacionales", "Negocios Internacionales", "C"),
        ("Liderazgo y Gestión", "Liderazgo", "D"),
        ("Liderazgo", "Liderazgo", "D"),
        ("Capital Humano", "Capital Humano", "E"),
        ("Emprendimiento", "Emprendimiento", "F"),
        ("Empresas Familiares", "Empresas Familiares", "G"),
        ("Inteligencia de Negocios", "Inteligencia de Negocios", "H"),
        ("Ventas", "Ventas", "I"),
        ("Sostenibilidad", "Sostenibilidad", "J"),
    ],
    "Ingeniería y Ciencias": [
        ("Administración de Proyectos y Desarrollo de Nuevos Productos", "Administración de Proyectos y Desarrollo de Nuevos Productos", "A"),
        ("Administracion de Proyectos y Desarrollo de Nuevos Productos", "Administración de Proyectos y Desarrollo de Nuevos Productos", "A"),
        ("Calidad", "Calidad", "B"),
        ("Diseño y Construcción", "Diseño y Construcción", "C"),
        ("Diseno y Construccion", "Diseño y Construcción", "C"),
        ("Agua, Energía y Medio Ambiente", "Agua, Energía y Medio Ambiente", "D"),
        ("Agua, Energia y Medio Ambiente", "Agua, Energía y Medio Ambiente", "D"),
        ("Innovación y Pensamiento Exponencial", "Innovación y Pensamiento Exponencial", "E"),
        ("Innovacion y Pensamiento Exponencial", "Innovación y Pensamiento Exponencial", "E"),
        ("Tecnologías de Información; Big Data y Data Analytics", "Tecnologías de Información; Big Data y Data Analytics", "F"),
        ("Tecnologias de Informacion Big Data y Data Analytics", "Tecnologías de Información; Big Data y Data Analytics", "F"),
        ("Alimentos", "Alimentos", "G"),
        ("Ciberseguridad", "Ciberseguridad", "H"),
        ("Industria 4.0", "Industria 4.0", "I"),
        ("Mecatrónica y Robótica", "Mecatrónica y Robótica", "J"),
        ("Mecatronica y Robotica", "Mecatrónica y Robótica", "J"),
        ("Manufactura", "Manufactura", "K"),
        ("Sostenibilidad", "Sostenibilidad", "L"),
    ],
    "Ciencias Sociales y Gobierno": [
        ("Finanzas públicas", "Finanzas públicas", "A"),
        ("Finanzas publicas", "Finanzas públicas", "A"),
        ("Ciudadanía", "Ciudadanía", "B"),
        ("Ciudadania", "Ciudadanía", "B"),
        ("Gestión Pública", "Gestión Pública", "C"),
        ("Gestion Publica", "Gestión Pública", "C"),
        ("Política Pública", "Política Pública", "D"),
        ("Politica Publica", "Política Pública", "D"),
        ("Gobernanza Metropolitana", "Gobernanza Metropolitana", "E"),
        ("Prevención y seguridad", "Prevención y seguridad", "F"),
        ("Prevencion y seguridad", "Prevención y seguridad", "F"),
        ("Transparencia y combate a la corrupción", "Transparencia y combate a la corrupción", "G"),
        ("Transparencia y combate a la corrupcion", "Transparencia y combate a la corrupción", "G"),
        ("Ciencia política", "Ciencia política", "H"),
        ("Ciencia politica", "Ciencia política", "H"),
        ("Relaciones Internacionales", "Relaciones Internacionales", "I"),
        ("Derecho", "Derecho", "J"),
        ("Desarrollo económico", "Desarrollo económico", "K"),
        ("Desarrollo economico", "Desarrollo económico", "K"),
        ("Política energética", "Política energética", "L"),
        ("Politica energetica", "Política energética", "L"),
        ("Sostenibilidad", "Sostenibilidad", "M"),
    ],
    "Medicina y Ciencias de la Salud": [
        ("Salud", "Salud", "A"),
        ("Nutrición", "Nutrición", "B"),
        ("Nutricion", "Nutrición", "B"),
        ("Psicología", "Psicología", "C"),
        ("Psicologia", "Psicología", "C"),
        ("Sostenibilidad", "Sostenibilidad", "D"),
    ],
    "Arquitectura y Diseño": [
        ("Arquitectura e Inmobiliaria", "Arquitectura e Inmobiliaria", "A"),
        ("Diseño", "Diseño", "B"),
        ("Diseno", "Diseño", "B"),
        ("Gestión y planeación urbana", "Gestión y planeación urbana", "C"),
        ("Gestion y planeacion urbana", "Gestión y planeación urbana", "C"),
        ("Resiliencia y desarrollo sostenible", "Resiliencia y desarrollo sostenible", "D"),
        ("Historia y Arte", "Historia y Arte", "E"),
        ("Animación y arte digital", "Animación y arte digital", "F"),
        ("Animacion y arte digital", "Animación y arte digital", "F"),
        ("Design thinking", "Design thinking", "G"),
        ("Tecnología aplicada al diseño", "Tecnología aplicada al diseño", "H"),
        ("Tecnologia aplicada al diseno", "Tecnología aplicada al diseño", "H"),
        ("Sostenibilidad", "Sostenibilidad", "I"),
    ],
    "Humanidades y Educación": [
        ("EHE", "EHE", "A"),
        ("Educación", "Educación", "B"),
        ("Educacion", "Educación", "B"),
        ("Idiomas", "Idiomas", "C"),
        ("Ética", "Ética", "D"),
        ("Etica", "Ética", "D"),
        ("Florecimiento humano y felicidad", "Florecimiento humano y felicidad", "E"),
        ("Sostenibilidad", "Sostenibilidad", "F"),
    ],
    "Multiescuela": [
        ("Mercadotecnia", "Mercadotecnia", "A"),
        ("Finanzas y Contabilidad", "Finanzas y Contabilidad", "B"),
        ("Negocios Internacionales", "Negocios Internacionales", "C"),
        ("Liderazgo", "Liderazgo", "D"),
        ("Capital Humano", "Capital Humano", "E"),
        ("Emprendimiento", "Emprendimiento", "F"),
        ("Empresas Familiares", "Empresas Familiares", "G"),
        ("Inteligencia de Negocios", "Inteligencia de Negocios", "H"),
        ("Ventas", "Ventas", "I"),
        ("Administración de Proyectos y Desarrollo de Nuevos Productos", "Administración de Proyectos y Desarrollo de Nuevos Productos", "J"),
        ("Administracion de Proyectos y Desarrollo de Nuevos Productos", "Administración de Proyectos y Desarrollo de Nuevos Productos", "J"),
        ("Calidad", "Calidad", "K"),
        ("Agua, Energía y Medio Ambiente", "Agua, Energía y Medio Ambiente", "L"),
        ("Agua, Energia y Medio Ambiente", "Agua, Energía y Medio Ambiente", "L"),
        ("Innovación", "Innovación", "M"),
        ("Innovacion", "Innovación", "M"),
        ("Tecnologías de Información; Big Data y Data Analytics", "Tecnologías de Información; Big Data y Data Analytics", "N"),
        ("Tecnologias de Informacion Big Data y Data Analytics", "Tecnologías de Información; Big Data y Data Analytics", "N"),
        ("Alimentos", "Alimentos", "O"),
        ("Industria 4.0", "Industria 4.0", "P"),
        ("Ciudadanía", "Ciudadanía", "Q"),
        ("Ciudadania", "Ciudadanía", "Q"),
        ("Gobernanza Metropolitana", "Gobernanza Metropolitana", "R"),
        ("Prevención y seguridad", "Prevención y seguridad", "S"),
        ("Prevencion y seguridad", "Prevención y seguridad", "S"),
        ("Transparencia y combate a la corrupción", "Transparencia y combate a la corrupción", "T"),
        ("Transparencia y combate a la corrupcion", "Transparencia y combate a la corrupción", "T"),
        ("Relaciones Internacionales", "Relaciones Internacionales", "U"),
        ("Desarrollo económico", "Desarrollo económico", "V"),
        ("Desarrollo economico", "Desarrollo económico", "V"),
        ("Política energética", "Política energética", "W"),
        ("Politica energetica", "Política energética", "W"),
        ("Salud", "Salud", "X"),
        ("Nutrición", "Nutrición", "Y"),
        ("Nutricion", "Nutrición", "Y"),
        ("Psicología", "Psicología", "Z"),
        ("Psicologia", "Psicología", "Z"),
        ("Diseño", "Diseño", "0"),
        ("Diseno", "Diseño", "0"),
        ("Gestión y planeación urbana", "Gestión y planeación urbana", "1"),
        ("Gestion y planeacion urbana", "Gestión y planeación urbana", "1"),
        ("Historia y Arte", "Historia y Arte", "2"),
        ("Animación y arte digital", "Animación y arte digital", "3"),
        ("Animacion y arte digital", "Animación y arte digital", "3"),
        ("Design thinking", "Design thinking", "4"),
        ("Tecnología aplicada al diseño", "Tecnología aplicada al diseño", "5"),
        ("Tecnologia aplicada al diseno", "Tecnología aplicada al diseño", "5"),
        ("Comunicación", "Comunicación", "6"),
        ("Comunicacion", "Comunicación", "6"),
        ("Educación", "Educación", "7"),
        ("Educacion", "Educación", "7"),
        ("Ética", "Ética", "8"),
        ("Etica", "Ética", "8"),
        ("Sostenibilidad", "Sostenibilidad", "9"),
    ],
}


# =============================================================================
# Transformaciones de negocio
# =============================================================================
def transform_campus(val):
    if val is None or pd.isna(val):
        return None
    key = norm_for_match(val)
    return CAMPUS_MAP_N.get(key, str(val).strip())


def transform_escuela(val):
    if val is None or pd.isna(val):
        return (None, None)

    s = str(val).strip()

    # Regla extra: si contiene coma => Multiescuela
    if "," in s:
        s2 = "Multiescuela"
    else:
        s2 = s

    n = norm_for_match(s2)
    escuela_final = ESCUELA_CODE_N.get(n, s2)
    escuela_categoria = ESCUELA_CATEGORIAS_CANON.get(n, s2 if s2 else None)

    return escuela_final, escuela_categoria


def transform_tipo_programa(val):
    if val is None or pd.isna(val):
        return None
    best = best_match_by_earliest_occurrence(val, TIPO_CANDIDATES)
    if best is None:
        return str(val).strip()
    return TIPO_TO_OUT.get(best, str(val).strip())


def transform_area_tematica(area_val, escuela_categoria):
    if area_val is None or pd.isna(area_val):
        return None
    if not escuela_categoria:
        return str(area_val).strip()

    escuela_cat = escuela_categoria

    if escuela_cat not in AREA_MAP:
        escuela_cat_n = norm_for_match(escuela_cat)
        for k in AREA_MAP.keys():
            if norm_for_match(k) == escuela_cat_n:
                escuela_cat = k
                break

    if escuela_cat not in AREA_MAP:
        return str(area_val).strip()

    candidates = [t[0] for t in AREA_MAP[escuela_cat]]
    best = best_match_by_earliest_occurrence(area_val, candidates)
    if best is None:
        return str(area_val).strip()

    for key, display, code in AREA_MAP[escuela_cat]:
        if key == best:
            return f"{display} {code}"

    return str(area_val).strip()


def transform_componente_tlg(val):
    if val is None or pd.isna(val):
        return None

    if isinstance(val, bool):
        return "Si" if val else "No"

    s = str(val).strip().lower()
    if s in ("true", "1", "si", "sí", "yes", "y"):
        return "Si"
    if s in ("false", "0", "no", "n"):
        return "No"

    try:
        n = int(float(s))
        return "Si" if n != 0 else "No"
    except Exception:
        return str(val).strip()


# =============================================================================
# Sanitizado para INSERT (evita NaN/Timestamp/errores ODBC)
# =============================================================================
MAXLEN = {
    "ID_Oportunidad": 50,
    "Nombre_usuario_solicitante": 250,
    "Correo_electronico_solicitante": 254,
    "Nomina_solicitante": 50,
    "Campus": 350,
    "Escuela": 350,
    "Area_tematica": 350,
    "Tipo_programa": 350,
    "Region": 120,
    "Proyecto_TLG": 200,
}
DATE_COLS = ["Fecha_inicial_programa", "Fecha_final_programa"]
DT_COLS = ["Fecha_actualizacion"]


def is_nullish(x) -> bool:
    if x is None:
        return True
    try:
        if x is pd.NaT:
            return True
    except Exception:
        pass
    if isinstance(x, float) and math.isnan(x):
        return True
    try:
        return bool(pd.isna(x))
    except Exception:
        return False


def to_varchar(x, maxlen: int):
    if is_nullish(x):
        return None
    s = str(x).strip()
    return s[:maxlen] if len(s) > maxlen else s


def to_date(x):
    if is_nullish(x):
        return None
    if isinstance(x, pd.Timestamp):
        if pd.isna(x):
            return None
        return x.to_pydatetime().date()
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    dt = pd.to_datetime(x, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.to_pydatetime().date()


def to_datetime2(x):
    if is_nullish(x):
        return None
    if isinstance(x, pd.Timestamp):
        if pd.isna(x):
            return None
        return x.to_pydatetime()  # Python datetime
    if isinstance(x, datetime):
        return x
    dt = pd.to_datetime(x, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.to_pydatetime()


def sanitize_df_for_insert(df_out: pd.DataFrame) -> pd.DataFrame:
    df = df_out.copy()

    # varchar: strings/None, dtype object (sin NaN)
    for col, ml in MAXLEN.items():
        if col in df.columns:
            df[col] = pd.Series([to_varchar(v, ml) for v in df[col].tolist()], dtype="object")

    # date: datetime.date/None, dtype object
    for col in DATE_COLS:
        if col in df.columns:
            df[col] = pd.Series([to_date(v) for v in df[col].tolist()], dtype="object")

    # datetime2: datetime.datetime (Python)/None, dtype object
    for col in DT_COLS:
        if col in df.columns:
            df[col] = pd.Series([to_datetime2(v) for v in df[col].tolist()], dtype="object")

    return df


# =============================================================================
# ETL
# =============================================================================
def borrar_tabla_destino(conn_edata):
    cur = conn_edata.cursor()
    try:
        cur.execute("TRUNCATE TABLE Edata_Qlik.dbo.PHub_Formato_Universal_Tabla;")
    except Exception:
        cur.execute("DELETE FROM Edata_Qlik.dbo.PHub_Formato_Universal_Tabla;")
    conn_edata.commit()


def extraer_fuentes(fecha_min_str="2023-08-01"):
    conn_pmo = crear_conexion_sql("BD_PMO")
    conn_edata = crear_conexion_sql("Edata_Qlik")

    try:
        # 2) Datos_CRM
        q_datos = """
            SELECT
                id_crm,
                id_asesor
            FROM BD_PMO.dbo.Datos_CRM
            WHERE fecha_cierre_ganada >= ?
        """
        df_datos = read_sql_df(conn_pmo, q_datos, params=[fecha_min_str])
        if df_datos.empty:
            return pd.DataFrame(), conn_pmo, conn_edata

        df_datos["id_crm"] = df_datos["id_crm"].astype(str).str.strip()
        df_datos["id_asesor"] = df_datos["id_asesor"].astype(str).str.strip()

        # 3) User_CRM por id_asesor
        asesores = sorted(df_datos["id_asesor"].dropna().unique().tolist())
        q_users_base = """
            SELECT
                id_crm AS id_asesor,
                nombre,
                No_Empleado,
                email
            FROM BD_PMO.dbo.User_CRM
            WHERE id_crm IN ({placeholders})
        """
        df_users = fetch_in_chunks(conn_pmo, q_users_base, asesores, chunk_size=900)

        # 4) Tableau_U4O_Historico por id_crm
        oportunidades = sorted(df_datos["id_crm"].dropna().unique().tolist())
        q_hist_base = """
            SELECT
                IdOportunidad,
                InicioEjecucion,
                TerminoEjecucion,
                CampusUsuario,
                Escuela,
                AreaTematica,
                TipoPrograma,
                ZonaAgrupada,
                ComponenteTLG
            FROM Edata_Qlik.dbo.Tableau_U4O_Historico
            WHERE IdOportunidad IN ({placeholders})
        """
        df_hist = fetch_in_chunks(conn_edata, q_hist_base, oportunidades, chunk_size=900)
        if not df_hist.empty:
            df_hist.rename(columns={"IdOportunidad": "id_crm"}, inplace=True)
            df_hist["id_crm"] = df_hist["id_crm"].astype(str).str.strip()

        # Merge
        df = df_datos.merge(df_users, on="id_asesor", how="left")
        df = df.merge(df_hist, on="id_crm", how="left")

        return df, conn_pmo, conn_edata

    except Exception:
        try:
            conn_pmo.close()
        except Exception:
            pass
        try:
            conn_edata.close()
        except Exception:
            pass
        raise


def transformar(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    # Campus (ya no dejará nan)
    df["Campus"] = df["CampusUsuario"].apply(transform_campus)

    # Escuela (final + categoría)
    escuela_t = df["Escuela"].apply(transform_escuela)
    df["Escuela_final"] = escuela_t.apply(lambda x: x[0])
    df["Escuela_categoria"] = escuela_t.apply(lambda x: x[1])

    # Tipo programa
    df["Tipo_programa"] = df["TipoPrograma"].apply(transform_tipo_programa)

    # Area temática (depende de escuela)
    df["Area_tematica"] = df.apply(
        lambda r: transform_area_tematica(r.get("AreaTematica"), r.get("Escuela_categoria")),
        axis=1
    )

    # Proyecto TLG
    df["Proyecto_TLG"] = df["ComponenteTLG"].apply(transform_componente_tlg)

    # Esquema destino
    out = pd.DataFrame({
        "ID_Oportunidad": df["id_crm"],
        "Nombre_usuario_solicitante": df.get("nombre"),
        "Correo_electronico_solicitante": df.get("email"),
        "Nomina_solicitante": df.get("No_Empleado"),
        "Fecha_inicial_programa": df.get("InicioEjecucion"),
        "Fecha_final_programa": df.get("TerminoEjecucion"),
        "Campus": df.get("Campus"),
        "Escuela": df.get("Escuela_final"),
        "Area_tematica": df.get("Area_tematica"),
        "Tipo_programa": df.get("Tipo_programa"),
        "Region": df.get("ZonaAgrupada"),
        "Proyecto_TLG": df.get("Proyecto_TLG"),
    })

    # Fecha_actualizacion: Python datetime puro, dtype object (no Timestamp)
    now_dt = datetime.now()
    out["Fecha_actualizacion"] = pd.Series([now_dt] * len(out), dtype="object")

    return out


def insertar_destino(conn_edata, df_out: pd.DataFrame) -> int:
    if df_out.empty:
        return 0

    insert_sql = """
        INSERT INTO Edata_Qlik.dbo.PHub_Formato_Universal_Tabla (
            ID_Oportunidad,
            Nombre_usuario_solicitante,
            Correo_electronico_solicitante,
            Nomina_solicitante,
            Fecha_inicial_programa,
            Fecha_final_programa,
            Campus,
            Escuela,
            Area_tematica,
            Tipo_programa,
            Region,
            Proyecto_TLG,
            Fecha_actualizacion
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """

    df_clean = sanitize_df_for_insert(df_out)

    cols_order = [
        "ID_Oportunidad",
        "Nombre_usuario_solicitante",
        "Correo_electronico_solicitante",
        "Nomina_solicitante",
        "Fecha_inicial_programa",
        "Fecha_final_programa",
        "Campus",
        "Escuela",
        "Area_tematica",
        "Tipo_programa",
        "Region",
        "Proyecto_TLG",
        "Fecha_actualizacion",
    ]
    df_clean = df_clean[cols_order]

    # Última defensa: convertir cada celda a Python puro
    def py_val(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        try:
            if pd.isna(v):
                return None
        except Exception:
            pass
        if isinstance(v, pd.Timestamp):
            return v.to_pydatetime()
        return v

    rows = [tuple(py_val(v) for v in row) for row in df_clean.itertuples(index=False, name=None)]

    # Cursor nuevo para evitar cacheo de tipos
    cur = conn_edata.cursor()
    try:
        cur.fast_executemany = False
    except Exception:
        pass

    try:
        cur.executemany(insert_sql, rows)
        conn_edata.commit()
        return len(rows)

    except Exception as e:
        conn_edata.rollback()
        print("\n[PHub_Formato_Universal][ERROR] Falló executemany. Buscando fila problemática...\n")

        for i, row in enumerate(rows):
            try:
                cur2 = conn_edata.cursor()
                cur2.execute(insert_sql, row)
            except Exception as e2:
                print(f"[PHub_Formato_Universal][BAD ROW] índice={i}")
                print("Valores y tipos:")
                for j, v in enumerate(row):
                    print(f"  col#{j+1}: {repr(v)}  (type={type(v)})")
                print("\nExcepción:", e2)
                raise
        raise


def imprimir_resumen(df_src: pd.DataFrame, df_out: pd.DataFrame, inserted: int, t0: datetime):
    total_src = len(df_src) if df_src is not None else 0
    total_out = len(df_out) if df_out is not None else 0

    faltan_user = 0
    faltan_hist = 0
    if df_src is not None and not df_src.empty:
        faltan_user = int(df_src["nombre"].isna().sum()) if "nombre" in df_src.columns else 0
        faltan_hist = int(df_src["InicioEjecucion"].isna().sum()) if "InicioEjecucion" in df_src.columns else 0

    dt_sec = (datetime.now() - t0).total_seconds()

    print("\n================= RESUMEN ETL: Formato Universal =================")
    print(f"Fecha/Hora inicio: {t0.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Tiempo total (seg): {dt_sec:,.2f}")
    print("------------------------------------------------------------------")
    print(f"Registros fuente (Datos_CRM filtrado): {total_src:,}")
    print(f"Registros salida (listos para insertar): {total_out:,}")
    print(f"Insertados en destino: {inserted:,}")
    print("------------------------------------------------------------------")
    print(f"Registros sin match en User_CRM (nombre NULL): {faltan_user:,}")
    print(f"Registros sin match en Tableau_U4O_Historico (InicioEjecucion NULL): {faltan_hist:,}")
    print("==================================================================\n")


def main(fecha_min="2023-08-01"):
    t0 = datetime.now()
    print(f"[PHub_Formato_Universal] Iniciando ETL. fecha_min={fecha_min}")

    df_src, conn_pmo, conn_edata = extraer_fuentes(fecha_min_str=fecha_min)

    try:
        if df_src.empty:
            print("[PHub_Formato_Universal] No hay registros en Datos_CRM para ese filtro. Fin.")
            return

        print(f"[PHub_Formato_Universal] Registros base extraídos: {len(df_src):,}")

        print("[PHub_Formato_Universal] Borrando contenido de Edata_Qlik.dbo.PHub_Formato_Universal_Tabla ...")
        borrar_tabla_destino(conn_edata)

        print("[PHub_Formato_Universal] Transformando datos ...")
        df_out = transformar(df_src)

        print("[PHub_Formato_Universal] Insertando en destino ...")
        inserted = insertar_destino(conn_edata, df_out)

        imprimir_resumen(df_src, df_out, inserted, t0)

    finally:
        try:
            conn_pmo.close()
        except Exception:
            pass
        try:
            conn_edata.close()
        except Exception:
            pass


if __name__ == "__main__":
    main(fecha_min="2023-08-01")