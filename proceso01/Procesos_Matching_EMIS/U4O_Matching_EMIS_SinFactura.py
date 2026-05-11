"""
Pipeline EMIS — Paso 2: enriquecimiento CRM para empresas SIN facturación.

DOCUMENTACIÓN COMPLETA: Manual_Usuario_Matching_EMIS.md (en esta carpeta).
Ahí están las reglas de negocio, modos Diario/Semanal, refresh selectivo
con firma del catálogo, y troubleshooting.

------------------------------------------------------------------------
QUÉ HACE ESTE ARCHIVO
------------------------------------------------------------------------
Para cada DUNS con Facturado=False y Revisado_CRM=False, busca posibles
IdsCRM y variantes en el catálogo CRM:
  - [ETL].[dbo].[Extraer_EmpresasU4O]   — TODAS las cuentas Salesforce
                                          (sin filtrar VEC_ID; queremos
                                          variantes de Account Id).
  - [ETL].[dbo].[EmpresasHomologadas]  — mapeo NombreOriginal ↔
                                          NombrePrincipal.

Algoritmo:
  1. Construye catálogo CRM (build_crm_catalog): agrupa por
     NombrePrincipal con sus variantes y todos los IdsCRM resueltos.
     Lookup Name → list[Id] preserva múltiples cuentas con mismo Name.
  2. Blocking + scoring CRM (re-pesado distinto al Paso 1 porque CRM no
     tiene Tradestyle/URL propios):
       55% best-of(nombre vs principal, nombre vs cada variante)
       20% trade vs variantes
       15% URL/dominio vs principal
       10% parent vs principal
  3. Decisión auto/LLM/descarte con los mismos umbrales 50/90 que Paso 1.
  4. LLM judge con prompt adaptado y cache separado:
       - cache_key(DUNS, NombrePrincipal) → cachea por GRUPO corporativo,
         no por cada Id (un mismo principal puede tener varios IdsCRM).
       - cache file: llm_cache_test_crm.json.

Persistencia:
  - Cada match enriquece in-place EMIS_Con_Historia_Fiscal.xlsx:
    Detalle_Matches.IdsCRM/Variantes_Nombre/Razones_LLM, Score_Max,
    Fuente_Match. IdsCliente/RFCs_Asociados/Regimenes_Fiscales SIEMPRE
    quedan vacíos (no facturó por definición).
  - Marca Revisado_CRM=True (procesado, no reprocesar en Diario).
  - Atomic write (.tmp.xlsx + os.replace) — robusto a Ctrl+C.
  - Flush incremental cada save_every (5 default) DUNS.

------------------------------------------------------------------------
CLASIFICACIONES Fuente_Match QUE ESTE PASO PRODUCE
------------------------------------------------------------------------
  - "crm_sin_factura_auto"  : todos los matches confirmados pasaron por
                              score > 90 (sin LLM).
  - "crm_sin_factura_llm"   : todos vinieron del LLM judge.
  - "crm_sin_factura_mixto" : el DUNS conectó con varios principales,
                              unos por score alto y otros por LLM.

------------------------------------------------------------------------
MODOS — controlados por refresh_crm
------------------------------------------------------------------------
Diario (refresh_crm=False):
  Procesa solo DUNS con Revisado_CRM=False. Estado estable: 0 pendientes.

Semanal (refresh_crm=True) — refresh selectivo:
  1. Calcula firma del catálogo CRM actual (hash16 por NombrePrincipal).
  2. Compara contra crm_catalog_signature.json de la corrida previa.
  3. Diff: principales_modificados / nuevos / eliminados.
  4. Resetea Revisado_CRM=False solo para los DUNS afectados:
       - con match: si alguna Variantes_Nombre mapea a un principal
                    modificado/eliminado.
       - sin match: TODOS, pero solo si hay principales nuevos.
  5. Persiste firma nueva al final.

  Primera corrida sin firma previa → fallback masivo (resetea todos los
  Facturado=False). Crea baseline para que la siguiente sea selectiva.

------------------------------------------------------------------------
INVOCACIÓN
------------------------------------------------------------------------
Programática (Paso 2 del orquestador, llamado por
U4O_Matching_EMIS_Fiscal.run_full_pipeline):
    run_crm_subprocess(origen, refresh_crm=False)

Standalone (CLI con argparse):
    python U4O_Matching_EMIS_SinFactura.py --origen Erik
    python U4O_Matching_EMIS_SinFactura.py --origen Erik --n 50
    python U4O_Matching_EMIS_SinFactura.py --origen Erik --duns 812768827
    python U4O_Matching_EMIS_SinFactura.py --origen Erik --refresh-crm
    python U4O_Matching_EMIS_SinFactura.py --origen Erik --no-mark   (dry-run)

------------------------------------------------------------------------
DECISIONES DE DISEÑO CLAVE
------------------------------------------------------------------------
1. Sin filtro VEC_ID_Empresa__c en la query: queremos variantes de
   Account Id. Excluir cuentas sin VEC perdería IdsCRM legítimos
   (caso Furukawa Automotive Systems Mexico).
2. name_to_ids_global como dict[Name, list[Id]]: dos cuentas SF distintas
   pueden compartir Name (case-insensitive). Lista preserva ambas.
3. Score CRM re-ponderado vs Paso 1: el catálogo no tiene URL/Tradestyle
   propios. Si reusáramos el score fiscal, ~45% del peso quedaría en 0
   y los matches válidos no superarían 55. El re-peso 55/20/15/10
   redistribuye sobre lo disponible.
4. Cache LLM por (DUNS, NombrePrincipal) — no por Id: la decisión es
   semántica del grupo corporativo, no del Id particular.
"""

import argparse
import json
import os
import sys
import time
import warnings
from collections import defaultdict

# Silenciar ruido de pandas 2.x (mismo patrón que U4O_Limpieza_Fiscal.py)
warnings.filterwarnings('ignore', category=UserWarning,
                        message=r'.*SQLAlchemy connectable.*')
warnings.filterwarnings('ignore', category=FutureWarning,
                        message=r'.*ChainedAssignmentError.*')

import pandas as pd
from openai import AzureOpenAI
from rapidfuzz import fuzz

# Permitir importar Conexiones desde la raíz del proyecto y
# importar U4O_Matching_EMIS_Fiscal por nombre simple incluso cuando este módulo
# se carga como parte del paquete (Procesos_Matching_EMIS.U4O_Matching_EMIS_SinFactura)
# desde otro directorio (por ejemplo, vía CierresU4O_Proceso01.py).
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(_BASE_DIR, "..")))
sys.path.insert(0, _BASE_DIR)
import Conexiones

# Reutilizar funciones y constantes del pipeline principal
from U4O_Matching_EMIS_Fiscal import (
    normalize_name,
    tokenize,
    extract_domain,
    SCORE_AUTO,
    SCORE_LLM,
    BATCH_SIZE,
    AZURE_ENDPOINT,
    AZURE_API_VERSION,
    LLM_MODEL,
    LLM_SYSTEM,
    _API_KEY_VAR,
    EMIS_PATH,
    OUTPUT_PATH as RESULT_XLSX_PATH,
    cache_key,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CRM_CACHE_PATH = os.path.join(BASE_DIR, "llm_cache_test_crm.json")
# Firma del catálogo CRM persistida entre corridas. Permite detección selectiva
# de cambios en el refresh: solo se reprocesan los DUNS cuyo NombrePrincipal
# asociado tiene hash distinto o desapareció, en vez de reprocesar todos.
CATALOG_SIGNATURE_PATH = os.path.join(BASE_DIR, "crm_catalog_signature.json")


# ---------------------------------------------------------------------------
# Firma del catálogo CRM (para refresh selectivo)
# ---------------------------------------------------------------------------
import hashlib  # local: solo para signature; el resto del cache_key viene del Fiscal


def _principal_signature(ids_crm: list, variantes: list) -> str:
    """Hash estable de un NombrePrincipal: sha256 corto sobre (IdsCRM ∪ Variantes) ordenados."""
    payload = "|".join(sorted(set(ids_crm))) + "::" + "|".join(sorted({v.strip().upper() for v in variantes if v}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def compute_catalog_signature(crm_df: pd.DataFrame) -> dict:
    """
    Construye {
        "principales": {NombrePrincipal: hash},
        "variant_to_principal": {VARIANTE_UPPER: NombrePrincipal}
    }
    Sirve para comparar contra una firma previa y detectar qué cambió.
    """
    principales = {}
    variant_to_principal = {}
    for _, row in crm_df.iterrows():
        principal = row["NombrePrincipal"]
        principales[principal] = _principal_signature(row["IdsCRM"], row["Variantes"])
        for v in row["Variantes"]:
            v_up = str(v).strip().upper()
            if v_up and v_up not in variant_to_principal:
                variant_to_principal[v_up] = principal
    return {"principales": principales, "variant_to_principal": variant_to_principal}


def load_previous_signature() -> dict | None:
    if not os.path.exists(CATALOG_SIGNATURE_PATH):
        return None
    try:
        with open(CATALOG_SIGNATURE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_catalog_signature(sig: dict):
    with open(CATALOG_SIGNATURE_PATH, "w", encoding="utf-8") as f:
        json.dump(sig, f, ensure_ascii=False, indent=2)


def affected_duns_from_signature_diff(prev_sig: dict, curr_sig: dict,
                                      df_resultado: pd.DataFrame) -> tuple[set, dict]:
    """
    Calcula el set de DUNS (Facturado=False) que deben reprocesarse según el
    diff entre la firma previa y la actual del catálogo.

    Reglas:
      - DUNS con match (IdsCRM no vacío en Detalle_Matches): se reprocesa si
        alguna de sus Variantes_Nombre mapea a un NombrePrincipal cuyo hash
        cambió, o que ya no existe en el catálogo nuevo.
      - DUNS sin_match (IdsCRM vacío): se reprocesan TODOS si en el catálogo
        nuevo aparecieron NombresPrincipales nuevos (porque ahora podrían
        encontrar match). Si solo hubo modificaciones/eliminaciones, los
        sin_match no se tocan.

    Retorna (set de DUNS afectados, dict con stats: {cambiados, nuevos, eliminados, con_match, sin_match}).
    """
    prev_principales = prev_sig.get("principales", {})
    curr_principales = curr_sig.get("principales", {})
    prev_v2p = prev_sig.get("variant_to_principal", {})

    set_prev = set(prev_principales.keys())
    set_curr = set(curr_principales.keys())

    eliminados = set_prev - set_curr
    nuevos = set_curr - set_prev
    modificados = {p for p in (set_prev & set_curr)
                   if prev_principales[p] != curr_principales[p]}

    afectados_principales = eliminados | modificados  # los nuevos NO afectan DUNS con match
    affected_duns = set()

    # DUNS con match: reset si alguna variante mapea a un principal afectado
    # DUNS sin match: si hay nuevos principales en el catálogo, todos se resetean
    cnt_con_match = 0
    cnt_sin_match = 0
    for _, row in df_resultado.iterrows():
        if bool(row.get("Facturado", False)):
            continue
        duns = str(row["D-U-N-S® Number"])
        try:
            obj = json.loads(row["Detalle_Matches"]) if isinstance(row["Detalle_Matches"], str) else {}
        except Exception:
            obj = {}
        ids_crm = obj.get("IdsCRM") or []
        variantes = obj.get("Variantes_Nombre") or []

        if ids_crm:
            for v in variantes:
                principal = prev_v2p.get(str(v).strip().upper())
                if principal and principal in afectados_principales:
                    affected_duns.add(duns)
                    cnt_con_match += 1
                    break
        else:
            # sin_match — solo se reprocesa si llegaron principales NUEVOS
            if nuevos:
                affected_duns.add(duns)
                cnt_sin_match += 1

    stats = {
        "principales_modificados": len(modificados),
        "principales_nuevos": len(nuevos),
        "principales_eliminados": len(eliminados),
        "duns_con_match_afectados": cnt_con_match,
        "duns_sin_match_afectados": cnt_sin_match,
    }
    return affected_duns, stats


# ---------------------------------------------------------------------------
# Columna de seguimiento Revisado_CRM
# ---------------------------------------------------------------------------
def _has_rfcs_asociados(detalle_val) -> bool:
    """True si Detalle_Matches.RFCs_Asociados tiene al menos un RFC."""
    if detalle_val is None or (isinstance(detalle_val, float) and pd.isna(detalle_val)):
        return False
    try:
        obj = json.loads(detalle_val) if isinstance(detalle_val, str) else detalle_val
        return bool(obj.get("RFCs_Asociados"))
    except Exception:
        return False


def ensure_revisado_crm_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Garantiza la columna 'Revisado_CRM' en el DataFrame del Excel resultado.
    Default cuando se crea: True si la fila ya tiene RFCs_Asociados (no
    requiere lookup CRM porque ya facturó), False en caso contrario.
    Idempotente: si ya existe, la respeta tal cual.
    """
    if "Revisado_CRM" in df.columns:
        # Normalizar dtype: pandas a veces deja NaN si la columna llegó con huecos
        df["Revisado_CRM"] = df["Revisado_CRM"].fillna(False).astype(bool)
        return df

    if "Detalle_Matches" in df.columns:
        df["Revisado_CRM"] = df["Detalle_Matches"].apply(_has_rfcs_asociados)
    elif "Facturado" in df.columns:
        df["Revisado_CRM"] = df["Facturado"].astype(bool)
    else:
        df["Revisado_CRM"] = False
    return df


def write_excel_atomic(df: pd.DataFrame):
    """
    Reescribe RESULT_XLSX_PATH con la hoja Matches_Detalle de forma atómica:
    escribe primero a un .tmp y al terminar hace os.replace al destino final.
    Así, si el proceso se interrumpe a media escritura, el Excel original
    no queda corrupto.

    Si Excel tiene el archivo abierto (lock '~$...xlsx'), aborta con mensaje claro.
    """
    lock_file = os.path.join(
        os.path.dirname(RESULT_XLSX_PATH),
        "~$" + os.path.basename(RESULT_XLSX_PATH),
    )
    if os.path.exists(lock_file):
        raise RuntimeError(
            f"El archivo está abierto en Excel ({lock_file}). "
            f"Ciérralo y vuelve a ejecutar."
        )
    # NOTA: pandas valida que la extensión sea .xlsx, por eso queda *.tmp.xlsx.
    _root, _ext = os.path.splitext(RESULT_XLSX_PATH)
    tmp_path = f"{_root}.tmp{_ext}"
    try:
        with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Matches_Detalle", index=False)
        os.replace(tmp_path, RESULT_XLSX_PATH)  # rename atómico — no deja archivo corrupto
    except Exception:
        # No dejar basura si algo falló a media escritura del .tmp
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def mark_duns_revisado(duns: str):
    """Marca Revisado_CRM=True para el DUNS dado y persiste el Excel."""
    df = pd.read_excel(
        RESULT_XLSX_PATH,
        sheet_name="Matches_Detalle",
        dtype={"D-U-N-S® Number": str},
    )
    df = ensure_revisado_crm_column(df)
    mask = df["D-U-N-S® Number"] == str(duns)
    if not mask.any():
        raise RuntimeError(f"DUNS {duns} no encontrado al persistir Revisado_CRM.")
    df.loc[mask, "Revisado_CRM"] = True
    write_excel_atomic(df)


def apply_crm_result_to_row(df: pd.DataFrame, duns: str, result: dict):
    """
    Actualiza in-memory la fila del DUNS con el resultado del sub-proceso CRM:
      - Detalle_Matches.IdsCRM         ← result["ids_crm"]      (sobrescribe)
      - Detalle_Matches.Variantes_Nombre ← result["variantes"]  (sobrescribe)
      - Detalle_Matches.Razones_LLM    ← result["razones_llm"]  (sobrescribe)
      - Score_Max                      ← result["score_max"]    (sobrescribe — antes era 0)
      - Fuente_Match                   ← result["fuente"]       (sobrescribe)
    NO toca: Facturado, Ultima_Facturacion, IdsCliente, RFCs_Asociados, Regimenes_Fiscales.
    NO escribe al disco — eso lo hace write_excel_atomic en el caller.
    """
    mask = df["D-U-N-S® Number"] == str(duns)
    if not mask.any():
        return

    # Parsear el JSON existente y actualizar solo las claves CRM
    detalle_actual = df.loc[mask, "Detalle_Matches"].iloc[0]
    try:
        obj = json.loads(detalle_actual) if isinstance(detalle_actual, str) else {}
        if not isinstance(obj, dict):
            obj = {}
    except Exception:
        obj = {}

    # Defaults si no existían las claves
    obj.setdefault("IdsCRM", [])
    obj.setdefault("IdsCliente", [])
    obj.setdefault("RFCs_Asociados", [])
    obj.setdefault("Regimenes_Fiscales", [])
    obj.setdefault("Variantes_Nombre", [])
    obj.setdefault("Razones_LLM", [])

    # Sobrescribir solo lo que el sub-proceso CRM produce
    obj["IdsCRM"] = list(result.get("ids_crm", []))
    obj["Variantes_Nombre"] = list(result.get("variantes", []))
    obj["Razones_LLM"] = list(result.get("razones_llm", []))

    df.loc[mask, "Detalle_Matches"] = json.dumps(obj, ensure_ascii=False)
    df.loc[mask, "Score_Max"] = float(result.get("score_max", 0.0))
    df.loc[mask, "Fuente_Match"] = result.get("fuente", "sin_match")


# ---------------------------------------------------------------------------
# Cache LLM (separado del de producción)
# ---------------------------------------------------------------------------
def load_crm_cache() -> dict:
    if os.path.exists(CRM_CACHE_PATH):
        with open(CRM_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_crm_cache(cache: dict):
    with open(CRM_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Catálogo CRM
# ---------------------------------------------------------------------------
def build_crm_catalog(origen: str) -> pd.DataFrame:
    """
    Construye el catálogo CRM uniendo:
      [ETL].[dbo].[Extraer_EmpresasU4O] (cuentas Salesforce sincronizadas en SQL)
      [ETL].[dbo].[EmpresasHomologadas] (mapeo NombreOriginal → NombrePrincipal)

    A diferencia de U4O_Limpieza_Fiscal.py, NO se filtra por facturas — se incluyen
    todas las empresas SF aunque no hayan facturado.

    Retorna DataFrame con columnas:
      NombrePrincipal, Variantes, IdsCRM, _principal_norm, _variantes_norm, _tokens
    """
    print(f"Conectando a [ETL] (origen='{origen}')...")
    conn, cursor = Conexiones.connect_ETL_local_sql(origen)
    if conn is None:
        raise RuntimeError(
            f"connect_ETL_local_sql('{origen}') retornó None. "
            f"Origen válido: 'Erik' o 'Antonio'."
        )

    try:
        print("Consultando Extraer_EmpresasU4O (TODAS las cuentas, sin filtro VEC_ID)...")
        df_sql = pd.read_sql(
            "SELECT Id, Name "
            "FROM [ETL].[dbo].[Extraer_EmpresasU4O] "
            "WHERE Name IS NOT NULL",
            conn,
        )
        df_sql.loc[:, "Name"] = df_sql["Name"].astype(str).str.strip()

        print("Consultando EmpresasHomologadas...")
        df_homo = pd.read_sql(
            "SELECT [NombreOriginal], [NombrePrincipal] "
            "FROM [ETL].[dbo].[EmpresasHomologadas]",
            conn,
        )
    finally:
        cursor.close()
        conn.close()

    # Lookup global Name(upper) → lista de IdEmpresa (Salesforce Account Ids).
    # IMPORTANTE: usamos lista (no string único) porque dos cuentas SF distintas
    # pueden tener el MISMO Name (case-insensitive); en ese caso ambas son
    # IdsCRM legítimos del mismo grupo y deben preservarse.
    name_to_ids_global = defaultdict(list)
    for _id, _n in zip(df_sql["Id"], df_sql["Name"]):
        if pd.isna(_id) or pd.isna(_n):
            continue
        key = str(_n).strip().upper()
        _id_str = str(_id).strip()
        if key and _id_str and _id_str not in name_to_ids_global[key]:
            name_to_ids_global[key].append(_id_str)

    # principal → set de variantes (incluye al propio principal)
    df_homo_clean = df_homo.dropna(subset=["NombreOriginal", "NombrePrincipal"]).reset_index(drop=True).copy()
    df_homo_clean.loc[:, "NombreOriginal"] = df_homo_clean["NombreOriginal"].astype(str).str.strip()
    df_homo_clean.loc[:, "NombrePrincipal"] = df_homo_clean["NombrePrincipal"].astype(str).str.strip()

    original_to_principal_upper = {
        row["NombreOriginal"].upper(): row["NombrePrincipal"]
        for _, row in df_homo_clean.iterrows()
    }
    all_known_principals_upper = {
        p.upper() for p in df_homo_clean["NombrePrincipal"].unique()
    }

    principal_to_variants = defaultdict(set)
    for _, row in df_homo_clean.iterrows():
        p = row["NombrePrincipal"]
        principal_to_variants[p].add(row["NombreOriginal"])
        principal_to_variants[p].add(p)  # el principal es variante de sí mismo

    # Cobertura adicional: empresas en SF que no aparecen en EmpresasHomologadas
    # se agregan como "principal sintético" para no perder cobertura.
    for name in df_sql["Name"].dropna().unique():
        n_clean = str(name).strip()
        if not n_clean:
            continue
        n_upper = n_clean.upper()
        if (
            n_upper not in original_to_principal_upper
            and n_upper not in all_known_principals_upper
        ):
            principal_to_variants[n_clean].add(n_clean)

    # Construir filas finales
    rows = []
    for principal, variantes_set in principal_to_variants.items():
        variantes = list(variantes_set)
        # Resolver IdsCRM: cada variante puede mapear a >=1 IdEmpresa
        # (cuentas SF distintas pueden compartir Name → preservamos todos).
        ids_crm = []
        seen_ids = set()
        for v in variantes:
            for _id in name_to_ids_global.get(v.strip().upper(), []):
                if _id not in seen_ids:
                    ids_crm.append(_id)
                    seen_ids.add(_id)
        # Si no hay ningún Id, omitir esta fila (no aporta IdsCRM)
        if not ids_crm:
            continue

        principal_norm = normalize_name(principal)
        variantes_norm = [normalize_name(v) for v in variantes]
        variantes_norm = [v for v in variantes_norm if v]

        tokens = set()
        for vn in variantes_norm:
            tokens |= tokenize(vn)
        if principal_norm:
            tokens |= tokenize(principal_norm)

        rows.append({
            "NombrePrincipal": principal,
            "Variantes": variantes,
            "IdsCRM": ids_crm,
            "_principal_norm": principal_norm,
            "_variantes_norm": variantes_norm,
            "_tokens": tokens,
        })

    crm_df = pd.DataFrame(rows).reset_index(drop=True)
    return crm_df


def build_crm_index(crm_df: pd.DataFrame) -> dict:
    """Índice invertido: token → [índices de fila CRM]."""
    index = {}
    for row_idx, row in crm_df.iterrows():
        for tok in row["_tokens"]:
            index.setdefault(tok, []).append(row_idx)
    return index


def get_crm_candidates(emis_row: pd.Series, crm_index: dict) -> set:
    """Candidatos CRM por token compartido con el EMIS (nombre + tradestyle + parent)."""
    tokens = (
        tokenize(emis_row["_nom"])
        | tokenize(emis_row["_trade"])
        | tokenize(emis_row["_parent"])
    )
    candidates = set()
    for tok in tokens:
        candidates.update(crm_index.get(tok, []))
    return candidates


# ---------------------------------------------------------------------------
# Scoring CRM
# ---------------------------------------------------------------------------
def score_pair_crm(emis_row: pd.Series, crm_row: pd.Series) -> dict:
    """
    Scoring adaptado a CRM: el catálogo CRM no tiene Tradestyle ni URL propios,
    por lo que se redistribuye el peso del score original hacia nombre/principal.

    Retorna dict con score y desglose para reporte en consola.
    """
    variantes_norm = crm_row["_variantes_norm"]
    principal_norm = crm_row["_principal_norm"] or ""

    # Nombre EMIS vs principal y vs cada variante (best-of)
    s_principal = fuzz.WRatio(emis_row["_nom"], principal_norm) if principal_norm else 0
    s_variantes = (
        max(fuzz.WRatio(emis_row["_nom"], v) for v in variantes_norm)
        if variantes_norm else 0
    )
    s_nombre = max(s_principal, s_variantes)

    # Tradestyle EMIS vs variantes
    s_trade = (
        max(fuzz.WRatio(emis_row["_trade"], v) for v in variantes_norm)
        if (emis_row["_trade"] and variantes_norm) else 0
    )

    # Parent EMIS vs principal
    s_parent = (
        fuzz.WRatio(emis_row["_parent"], principal_norm)
        if (emis_row["_parent"] and principal_norm) else 0
    )

    # URL: dominio EMIS vs principal normalizado
    dom = emis_row["_domain"]
    s_url = 100 if (dom and principal_norm and dom in principal_norm.lower()) else 0

    score = (
        s_nombre * 0.55 +
        s_trade  * 0.20 +
        s_url    * 0.15 +
        s_parent * 0.10
    )
    return {
        "score": round(score, 2),
        "s_nombre": s_nombre,
        "s_trade": s_trade,
        "s_url": s_url,
        "s_parent": s_parent,
    }


# ---------------------------------------------------------------------------
# LLM judge (adaptado a CRM)
# ---------------------------------------------------------------------------
def _build_pair_block_crm(idx: int, emis_row: pd.Series, crm_row: pd.Series) -> str:
    variantes = crm_row["Variantes"]
    # Mostrar hasta 5 variantes para no inflar el prompt
    variantes_show = variantes[:5]
    extra = f" (+{len(variantes) - 5} más)" if len(variantes) > 5 else ""
    variantes_str = json.dumps(variantes_show, ensure_ascii=False) + extra

    return (
        f"PAR {idx}:\n"
        f"  EMIS - Company Name: \"{emis_row.get('Company Name', '')}\"\n"
        f"       - Tradestyle: \"{emis_row.get('Tradestyle', '')}\"\n"
        f"       - URL: {emis_row.get('URL', '')}\n"
        f"       - Parent: \"{emis_row.get('Parent Company', '')}\"\n"
        f"       - Global Ultimate: \"{emis_row.get('Global Ultimate Company', '')}\"\n"
        f"  CRM  - NombrePrincipal: \"{crm_row['NombrePrincipal']}\"\n"
        f"       - Variantes: {variantes_str}\n"
        f"       - IdsCRM_count: {len(crm_row['IdsCRM'])}"
    )


def llm_judge_batch_crm(pairs: list, emis_row: pd.Series, crm_df: pd.DataFrame,
                        cache: dict, client: AzureOpenAI) -> list:
    """
    Evalúa un lote de pares EMIS↔CRM en una sola llamada LLM.
    Cache key: (DUNS, NombrePrincipal) — cachea decisión por grupo corporativo.
    Retorna lista de {'match': bool, 'razon': str} en el mismo orden.
    """
    duns = str(emis_row.get("D-U-N-S® Number", ""))

    results = [None] * len(pairs)
    pendientes = []

    for i, pair in enumerate(pairs):
        crm_row = crm_df.loc[pair["c_idx"]]
        key = cache_key(duns, crm_row["NombrePrincipal"])
        if key in cache:
            results[i] = cache[key]
        else:
            pendientes.append(i)

    if not pendientes:
        return results

    bloques = []
    for seq, i in enumerate(pendientes, 1):
        pair = pairs[i]
        crm_row = crm_df.loc[pair["c_idx"]]
        bloques.append(_build_pair_block_crm(seq, emis_row, crm_row))

    n = len(pendientes)
    prompt = (
        f"Evalúa los siguientes {n} pares (EMIS ↔ CRM).\n"
        f"Para cada PAR responde si la empresa EMIS y el grupo corporativo CRM "
        f"corresponden a la misma entidad o grupo.\n\n"
        + "\n\n".join(bloques)
        + f"\n\nResponde ÚNICAMENTE con un array JSON de {n} objetos en el mismo orden:\n"
        f'[{{"par": 1, "match": true/false, "razon": "..."}}, ...]'
    )

    t_inicio = time.time()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        max_tokens=150 * n,
        messages=[
            {"role": "system", "content": LLM_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    segundos = time.time() - t_inicio
    tokens_in = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens
    print(f"  LLM lote {n} pares → {segundos:.1f}s | "
          f"{segundos/n:.2f}s/par | tokens: {tokens_in} in / {tokens_out} out")

    raw = response.choices[0].message.content.strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
    except json.JSONDecodeError:
        import re
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        try:
            parsed = json.loads(m.group()) if m else []
        except Exception:
            parsed = []

    for seq_idx, i in enumerate(pendientes):
        pair = pairs[i]
        crm_row = crm_df.loc[pair["c_idx"]]
        key = cache_key(duns, crm_row["NombrePrincipal"])
        if seq_idx < len(parsed):
            res = {
                "match": bool(parsed[seq_idx].get("match")),
                "razon": parsed[seq_idx].get("razon", ""),
            }
        else:
            res = {"match": False, "razon": "parse_error"}
        cache[key] = res
        results[i] = res

    save_crm_cache(cache)
    return results


# ---------------------------------------------------------------------------
# Carga de Excels y selección de DUNS pendientes
# ---------------------------------------------------------------------------
def load_excels():
    """Carga el Excel de resultado (con Revisado_CRM garantizado) y el catálogo EMIS."""
    print("Cargando EMIS_Con_Historia_Fiscal.xlsx...")
    df_resultado = pd.read_excel(
        RESULT_XLSX_PATH,
        sheet_name="Matches_Detalle",
        dtype={"D-U-N-S® Number": str},
    )

    column_was_missing = "Revisado_CRM" not in df_resultado.columns
    df_resultado = ensure_revisado_crm_column(df_resultado)
    if column_was_missing:
        print("Columna 'Revisado_CRM' no existía — creada con default basado en RFCs_Asociados.")
        write_excel_atomic(df_resultado)
        n_rev = int(df_resultado["Revisado_CRM"].sum())
        n_pen = int((~df_resultado["Revisado_CRM"]).sum())
        print(f"  → {n_rev} marcados Revisado_CRM=True (ya tenían RFC), {n_pen} pendientes.")

    print("Cargando EMIS_Clasificado_Completo.xlsx (NACIONAL)...")
    df_emis = pd.read_excel(
        EMIS_PATH,
        sheet_name="NACIONAL",
        dtype={"D-U-N-S® Number": str},
    )
    return df_resultado, df_emis


def pick_duns_to_process(df_resultado: pd.DataFrame, args) -> list:
    """
    Devuelve la lista de DUNS a procesar en esta corrida.
    - Si --duns: lista con ese único DUNS.
    - Si --all : todos los pendientes (Facturado=False AND Revisado_CRM=False).
    - Si no    : muestra de tamaño args.n entre los pendientes (random_state=seed).
    """
    if args.duns is not None:
        sel = df_resultado[df_resultado["D-U-N-S® Number"] == str(args.duns)]
        if sel.empty:
            raise ValueError(f"DUNS '{args.duns}' no encontrado en {RESULT_XLSX_PATH}")
        if bool(sel.iloc[0]["Facturado"]):
            print(f"AVISO: el DUNS {args.duns} ya tiene Facturado=True; se procesa por petición explícita.")
        if bool(sel.iloc[0].get("Revisado_CRM", False)):
            print(f"AVISO: el DUNS {args.duns} ya está Revisado_CRM=True; se reprocesa por petición explícita.")
        return [str(args.duns)]

    pendientes = df_resultado[
        (df_resultado["Facturado"] == False) & (df_resultado["Revisado_CRM"] == False)
    ]
    if pendientes.empty:
        print("No hay EMIS pendientes (Facturado=False AND Revisado_CRM=False).")
        return []
    print(f"Pendientes de revisión CRM: {len(pendientes):,}")

    # Default (sin --n ni --all): procesar TODOS los pendientes.
    # Solo se acota la corrida si el usuario pasa --n N explícito.
    if args.all or args.n is None:
        return pendientes["D-U-N-S® Number"].astype(str).tolist()

    n = min(args.n, len(pendientes))
    sample = pendientes.sample(n=n, random_state=args.seed)
    return sample["D-U-N-S® Number"].astype(str).tolist()


def build_emis_row(target_duns: str, df_emis: pd.DataFrame, df_resultado: pd.DataFrame) -> pd.Series:
    """Construye la fila EMIS enriquecida con campos normalizados para scoring."""
    emis_match = df_emis[df_emis["D-U-N-S® Number"] == target_duns]
    if emis_match.empty:
        raise RuntimeError(f"DUNS {target_duns} no encontrado en hoja NACIONAL de {EMIS_PATH}.")
    emis_row = emis_match.iloc[0].copy()

    emis_row["_nom"]    = normalize_name(emis_row.get("Company Name", ""))
    emis_row["_trade"]  = normalize_name(emis_row.get("Tradestyle", ""))
    emis_row["_parent"] = normalize_name(emis_row.get("Parent Company", ""))
    emis_row["_global"] = normalize_name(emis_row.get("Global Ultimate Company", ""))
    emis_row["_domain"] = extract_domain(emis_row.get("URL", ""))
    res_row = df_resultado[df_resultado["D-U-N-S® Number"] == target_duns]
    emis_row["_facturado_actual"] = bool(res_row.iloc[0]["Facturado"]) if not res_row.empty else False
    return emis_row


# ---------------------------------------------------------------------------
# Procesamiento de UN DUNS (asume catálogo CRM ya cargado)
# ---------------------------------------------------------------------------
def process_one_duns(emis_row: pd.Series, crm_df: pd.DataFrame, crm_index: dict,
                     cache: dict, client: AzureOpenAI | None, top_n: int) -> dict:
    """
    Procesa un único DUNS: blocking → scoring → LLM → recomendación.
    Imprime sección compacta. Retorna dict con resumen para el resumen final.
    """
    duns = str(emis_row.get("D-U-N-S® Number", ""))

    print()
    print("─" * 70)
    print(f"DUNS {duns}  |  {emis_row.get('Company Name', '')}")
    print(f"  Tradestyle: {emis_row.get('Tradestyle','')}  |  URL: {emis_row.get('URL','')}")
    print(f"  Parent:     {emis_row.get('Parent Company','')}  |  Global: {emis_row.get('Global Ultimate Company','')}")

    candidates = get_crm_candidates(emis_row, crm_index)
    if not candidates:
        print(f"  → sin candidatos por blocking — sin_match")
        return {"duns": duns, "decision": "sin_match", "ids_crm": [], "variantes": [],
                "score_max": 0.0, "fuente": "sin_match", "razon": "sin candidatos por blocking"}

    # Scoring
    scored = []
    for c_idx in candidates:
        sd = score_pair_crm(emis_row, crm_df.loc[c_idx])
        scored.append({"c_idx": c_idx, "score": sd["score"]})
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[: top_n]

    auto_idx, llm_idx = [], []
    for i, p in enumerate(top):
        if p["score"] > SCORE_AUTO:
            auto_idx.append(i)
        elif p["score"] >= SCORE_LLM:
            llm_idx.append(i)

    llm_results_by_top_idx = {}
    if llm_idx and client is not None:
        pending_pairs = [{"c_idx": top[i]["c_idx"]} for i in llm_idx]
        all_resps = [None] * len(pending_pairs)
        for lote_inicio in range(0, len(pending_pairs), BATCH_SIZE):
            lote = pending_pairs[lote_inicio: lote_inicio + BATCH_SIZE]
            resps = llm_judge_batch_crm(lote, emis_row, crm_df, cache, client)
            for j, r in enumerate(resps):
                all_resps[lote_inicio + j] = r
        for j, top_i in enumerate(llm_idx):
            llm_results_by_top_idx[top_i] = all_resps[j] or {"match": False, "razon": "sin_respuesta"}

    # Tabla compacta del top
    print(f"  Candidatos: {len(candidates)}  |  Top {len(top)} → ", end="")
    decisions_count = {"AUTO": len(auto_idx),
                       "LLM_MATCH": sum(1 for r in llm_results_by_top_idx.values() if r["match"]),
                       "LLM_NO":    sum(1 for r in llm_results_by_top_idx.values() if not r["match"]),
                       "DESCARTE":  len(top) - len(auto_idx) - len(llm_results_by_top_idx)}
    print(", ".join(f"{k}={v}" for k, v in decisions_count.items() if v))

    for i, p in enumerate(top, 1):
        crm_row = crm_df.loc[p["c_idx"]]
        if (i - 1) in auto_idx:
            decision = "AUTO"
        elif (i - 1) in llm_results_by_top_idx:
            decision = "LLM→OK" if llm_results_by_top_idx[i - 1]["match"] else "LLM→NO"
        else:
            decision = "—"
        principal_short = (crm_row["NombrePrincipal"] or "")[:38]
        print(f"    [{i:>2}] score={p['score']:5.1f}  {decision:<7}  "
              f"{principal_short:<40}  ids={len(crm_row['IdsCRM'])}")

    for top_i, res in sorted(llm_results_by_top_idx.items()):
        if res["match"]:
            crm_row = crm_df.loc[top[top_i]["c_idx"]]
            print(f"    razón [{top_i+1}] {crm_row['NombrePrincipal'][:30]}: {res.get('razon','')[:80]}")

    # Recomendación
    matched_top_idx = sorted(set(
        list(auto_idx) + [i for i, r in llm_results_by_top_idx.items() if r["match"]]
    ))

    if not matched_top_idx:
        print(f"  RESULTADO: sin_match")
        return {"duns": duns, "decision": "sin_match", "ids_crm": [], "variantes": [],
                "score_max": (top[0]["score"] if top else 0.0),
                "fuente": "sin_match", "razones_llm": []}

    ids_crm_final, variantes_final, razones_llm_final = [], [], []
    seen_ids, seen_vars, seen_razones = set(), set(), set()
    fuentes = set()
    score_max = 0.0
    for ti in matched_top_idx:
        crm_row = crm_df.loc[top[ti]["c_idx"]]
        score_max = max(score_max, top[ti]["score"])
        es_auto = ti in auto_idx
        fuentes.add("auto" if es_auto else "llm")
        for _id in crm_row["IdsCRM"]:
            if _id not in seen_ids:
                ids_crm_final.append(_id)
                seen_ids.add(_id)
        for v in crm_row["Variantes"]:
            v_clean = str(v).strip()
            if v_clean and v_clean.upper() not in seen_vars:
                variantes_final.append(v_clean)
                seen_vars.add(v_clean.upper())
        # Razones LLM de los matches confirmados por LLM
        if not es_auto and ti in llm_results_by_top_idx:
            r = (llm_results_by_top_idx[ti].get("razon") or "").strip()
            if r and r not in seen_razones:
                razones_llm_final.append(r)
                seen_razones.add(r)

    fuente_label = (
        "crm_sin_factura_mixto" if {"auto", "llm"} <= fuentes
        else f"crm_sin_factura_{next(iter(fuentes))}"
    )
    print(f"  RESULTADO: match  |  {len(ids_crm_final)} IdsCRM, {len(variantes_final)} variantes, "
          f"score_max={score_max:.1f}, fuente={fuente_label}")
    return {"duns": duns, "decision": "match", "ids_crm": ids_crm_final,
            "variantes": variantes_final, "score_max": score_max,
            "fuente": fuente_label, "razones_llm": razones_llm_final}


# ---------------------------------------------------------------------------
# Flujo principal (batch)
# ---------------------------------------------------------------------------
def run_batch(args):
    df_resultado, df_emis = load_excels()

    # Catálogo CRM cargado UNA sola vez. Se construye AHORA (antes del refresh)
    # porque la firma actual se necesita para el diff selectivo del refresh.
    crm_df = build_crm_catalog(args.origen)
    crm_index = build_crm_index(crm_df)
    total_ids = sum(len(r["IdsCRM"]) for _, r in crm_df.iterrows())
    print(f"Catálogo CRM: {len(crm_df):,} principales, {total_ids:,} IdsCRM totales.")
    curr_signature = compute_catalog_signature(crm_df)

    # --refresh-crm: revalidar Facturado=False contra el catálogo CRM actual.
    # SELECTIVO: si existe firma previa, solo se resetean los DUNS cuyo
    # NombrePrincipal asociado cambió o desapareció (más DUNS sin_match si
    # llegaron principales nuevos al catálogo).
    # FALLBACK MASIVO: si no hay firma previa (primera corrida con esta lógica),
    # resetea todos los Facturado=False — es la base para el siguiente diff.
    if getattr(args, "refresh_crm", False):
        prev_signature = load_previous_signature()
        if prev_signature is None:
            mask_no_fact = (df_resultado["Facturado"] == False)
            n_reset = int((mask_no_fact & (df_resultado["Revisado_CRM"] == True)).sum())
            df_resultado.loc[mask_no_fact, "Revisado_CRM"] = False
            print(f"--refresh-crm (sin firma previa, fallback masivo): "
                  f"{n_reset} marcas reseteadas para Facturado=False.")
        else:
            affected_duns, stats = affected_duns_from_signature_diff(
                prev_signature, curr_signature, df_resultado
            )
            mask_affected = df_resultado["D-U-N-S® Number"].astype(str).isin(affected_duns)
            n_reset = int((mask_affected & (df_resultado["Revisado_CRM"] == True)).sum())
            df_resultado.loc[mask_affected, "Revisado_CRM"] = False
            print("--refresh-crm SELECTIVO (diff vs firma previa):")
            print(f"  Principales en catálogo: modificados={stats['principales_modificados']}, "
                  f"nuevos={stats['principales_nuevos']}, eliminados={stats['principales_eliminados']}")
            print(f"  DUNS afectados: con_match={stats['duns_con_match_afectados']}, "
                  f"sin_match={stats['duns_sin_match_afectados']}")
            print(f"  Total marcas reseteadas: {n_reset}")
        if not args.no_mark and n_reset > 0:
            write_excel_atomic(df_resultado)

    duns_list = pick_duns_to_process(df_resultado, args)

    if not duns_list:
        print("\nNada que procesar — sub-proceso CRM finaliza sin trabajo.")
        # Aun así persistimos la firma actual para que la próxima corrida
        # tenga base de comparación.
        if not args.no_mark:
            save_catalog_signature(curr_signature)
        return

    print()
    print("=" * 70)
    print(f"PROCESANDO {len(duns_list)} DUNS EN ESTA CORRIDA")
    print("=" * 70)

    cache = load_crm_cache()
    client = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=os.environ[_API_KEY_VAR],
        api_version=AZURE_API_VERSION,
    )

    summary = {"total": len(duns_list), "match": 0, "sin_match": 0, "error": 0,
               "results": []}
    saves_pending = 0  # contador para flush incremental

    try:
        for i, duns in enumerate(duns_list, 1):
            print()
            print(f"[{i}/{len(duns_list)}]", end=" ")
            try:
                emis_row = build_emis_row(duns, df_emis, df_resultado)
                result = process_one_duns(emis_row, crm_df, crm_index, cache, client, args.top_n)
                summary["results"].append(result)
                if result["decision"] == "match":
                    summary["match"] += 1
                else:
                    summary["sin_match"] += 1
            except Exception as e:
                print(f"ERROR procesando DUNS {duns}: {e}")
                summary["error"] += 1
                summary["results"].append({"duns": duns, "decision": "error", "razon": str(e),
                                           "ids_crm": [], "variantes": [], "score_max": 0.0,
                                           "fuente": "error"})

            # Marcar in-memory; flush al disco cada save_every (o al final)
            if not args.no_mark:
                # Si hubo match CRM, escribir IdsCRM, Variantes_Nombre, Score_Max, Fuente_Match
                if result.get("decision") == "match":
                    apply_crm_result_to_row(df_resultado, duns, result)
                # En todos los casos (match o sin_match) marcar como revisado
                mask = df_resultado["D-U-N-S® Number"] == duns
                df_resultado.loc[mask, "Revisado_CRM"] = True
                saves_pending += 1
                if saves_pending >= args.save_every:
                    write_excel_atomic(df_resultado)
                    print(f"  ✓ Excel actualizado ({saves_pending} marcas persistidas)")
                    saves_pending = 0
    finally:
        # Flush final de marcas pendientes (también en caso de excepción/Ctrl+C)
        if saves_pending > 0 and not args.no_mark:
            try:
                write_excel_atomic(df_resultado)
                print(f"\n✓ Excel actualizado al cierre ({saves_pending} marcas persistidas)")
            except Exception as e:
                print(f"\n⚠ No se pudo persistir Revisado_CRM al cierre: {e}")
        # Persistir firma del catálogo para que el próximo refresh sea selectivo.
        # Aunque la corrida fuera interrumpida, la firma actual sirve de base.
        if not args.no_mark:
            try:
                save_catalog_signature(curr_signature)
            except Exception as e:
                print(f"⚠ No se pudo persistir firma del catálogo CRM: {e}")

    # Resumen final
    print()
    print("=" * 70)
    print("RESUMEN DE LA CORRIDA")
    print("=" * 70)
    print(f"  Total procesados: {summary['total']}")
    print(f"  Con match CRM:    {summary['match']}")
    print(f"  Sin match:        {summary['sin_match']}")
    print(f"  Errores:          {summary['error']}")

    # Mostrar pendientes que quedan
    if not args.no_mark:
        df_check = pd.read_excel(RESULT_XLSX_PATH, sheet_name="Matches_Detalle",
                                 dtype={"D-U-N-S® Number": str})
        df_check = ensure_revisado_crm_column(df_check)
        n_pend = int(((df_check["Facturado"] == False) & (df_check["Revisado_CRM"] == False)).sum())
        print(f"  Pendientes restantes: {n_pend}")


def run_crm_subprocess(origen: str, n: int | None = None, top_n: int = 10,
                       save_every: int = 5, no_mark: bool = False,
                       seed: int = 42, duns: str | None = None,
                       refresh_crm: bool = False):
    """
    Punto de entrada programático del sub-proceso CRM.
    Pensado para ser invocado desde U4O_Matching_EMIS_Fiscal.py como Paso 2,
    o desde otros scripts. main() lo llama también con args de CLI.

    refresh_crm=True resetea Revisado_CRM=False para todos los Facturado=False
    antes de procesar — útil para revalidar matches contra cambios en SF.
    """
    args = argparse.Namespace(
        origen=origen, duns=duns, n=n, all=(n is None and duns is None),
        seed=seed, top_n=top_n, save_every=save_every, no_mark=no_mark,
        refresh_crm=refresh_crm,
    )
    run_batch(args)


def main():
    parser = argparse.ArgumentParser(
        description="Enriquecimiento CRM para EMIS sin facturación (procesa N por corrida)."
    )
    parser.add_argument("--origen", type=str, required=True,
                        help="Parámetro para connect_ETL_local_sql ('Erik' o 'Antonio').")
    parser.add_argument("--duns", type=str, default=None,
                        help="DUNS específico a procesar (anula --n y --all).")
    parser.add_argument("--n", type=int, default=None,
                        help="Cantidad de DUNS a procesar (muestra random). "
                             "Si se omite, se procesan TODOS los pendientes.")
    parser.add_argument("--all", action="store_true",
                        help="Alias explícito: procesar TODOS los pendientes (= sin --n).")
    parser.add_argument("--seed", type=int, default=42,
                        help="Semilla para el sample aleatorio de pendientes.")
    parser.add_argument("--top-n", type=int, default=10,
                        help="Candidatos top a evaluar por DUNS (default 10).")
    parser.add_argument("--save-every", type=int, default=5,
                        help="Cada cuántos DUNS marcados se hace flush al Excel (default 5).")
    parser.add_argument("--no-mark", action="store_true",
                        help="No marcar Revisado_CRM=True ni escribir Excel (modo dry-run).")
    parser.add_argument("--refresh-crm", action="store_true",
                        help="Resetea Revisado_CRM=False para todos los Facturado=False y reprocesa "
                             "(uso típico: 1 vez por semana, para capturar nuevas variantes/IdsCRM "
                             "que llegaron a SF desde la última corrida). El cache LLM mitiga el costo.")
    args = parser.parse_args()
    run_batch(args)


if __name__ == "__main__":
    main()
