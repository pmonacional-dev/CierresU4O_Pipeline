"""
Pipeline EMIS — Paso 1 (matching fiscal) + orquestador del Paso 2.

DOCUMENTACIÓN COMPLETA: Manual_Usuario_Matching_EMIS.md (en esta carpeta).
Ahí están los algoritmos, reglas de negocio, modos Diario/Semanal,
clasificaciones de Fuente_Match y troubleshooting.

------------------------------------------------------------------------
QUÉ HACE ESTE ARCHIVO
------------------------------------------------------------------------
Paso 1 — matching por similitud de nombre entre cada EMIS y el catálogo
fiscal (Reporte_Fiscal_Historico.csv, ~775 empresas que SÍ facturaron):

  1. Normaliza nombres (NFD → ASCII, quita sufijos legales, mayúsculas).
  2. Blocking por índice invertido de tokens significativos.
  3. Score ponderado:
       40% nombre, 20% tradestyle, 25% URL/dominio, 15% parent.
  4. Decisión:
       score > 90    → match auto.
       50–90         → cola LLM (gpt-4.1-mini en Azure).
       < 50          → descarte.
  5. LLM judge en lotes de 10 con cache por (DUNS, RFC).

Paso 2 — sub-proceso CRM. Para los EMIS Facturado=False, busca IdsCRM
y variantes en [ETL].[dbo].[Extraer_EmpresasU4O] + EmpresasHomologadas.
Lo invoca run_full_pipeline() vía U4O_Matching_EMIS_SinFactura.

------------------------------------------------------------------------
CLASIFICACIONES Fuente_Match QUE ESTE PASO PRODUCE
------------------------------------------------------------------------
  - "auto"      : match con score > 90, sin LLM (alineación casi literal).
  - "llm"       : match en cola 50-90 confirmado por el LLM judge. Si en
                  el grupo del DUNS hay ≥1 LLM positivo, toda la fila se
                  marca 'llm'.
  - "sin_match" : ningún candidato pasó (también si Paso 2 no encontró
                  nada después).

Las clasificaciones 'crm_sin_factura_*' las produce el Paso 2.

------------------------------------------------------------------------
SALIDA
------------------------------------------------------------------------
Procesos_Matching_EMIS/EMIS_Con_Historia_Fiscal.xlsx (hoja Matches_Detalle):
  D-U-N-S® Number | Company Name | Facturado | Revisado_CRM
  | Detalle_Matches (JSON: IdsCRM, IdsCliente, RFCs_Asociados,
                     Regimenes_Fiscales, Variantes_Nombre, Razones_LLM)
  | Ultima_Facturacion | Score_Max | Fuente_Match

------------------------------------------------------------------------
INVOCACIÓN
------------------------------------------------------------------------
Programática (orquestador CierresU4O_Proceso01.py: run_main_25):
    main(origen, periodo)
        periodo="Diario"  → procesa solo pendientes en Paso 2.
        periodo="Semanal" → refresh selectivo en Paso 2 (revalida los
                            DUNS afectados por cambios en el catálogo CRM).

Standalone:
    python U4O_Matching_EMIS_Fiscal.py --origen Erik --periodo Diario
    python U4O_Matching_EMIS_Fiscal.py --origen Erik --periodo Semanal
    python U4O_Matching_EMIS_Fiscal.py --origen Erik --skip-crm

------------------------------------------------------------------------
DECISIÓN DE DISEÑO CLAVE
------------------------------------------------------------------------
El matching es por NOMBRE, no por RFC. Razón: solo ~5.6% de EMIS tiene
factura; matchear por RFC dejaría fuera el 94% restante. La similitud
de nombre + URL + parent funciona como matching universal y el LLM
judge resuelve la ambigüedad de score 50-90.
"""

import hashlib
import json
import os
import re
import unicodedata
from urllib.parse import urlparse

import openai
from openai import AzureOpenAI
import pandas as pd
from rapidfuzz import fuzz
from dotenv import load_dotenv

# Carga .env desde la raíz del proyecto (un nivel arriba de Procesos_Matching_EMIS/)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

# ---------------------------------------------------------------------------
# Variables de entorno requeridas
# ---------------------------------------------------------------------------
_API_KEY_VAR = "OPENAI_API_KEY_ITESM"
if not os.environ.get(_API_KEY_VAR):
    raise EnvironmentError(
        f"Variable de entorno '{_API_KEY_VAR}' no configurada.\n"
        f"Configúrala antes de ejecutar:  set {_API_KEY_VAR}=<tu_clave>"
    )

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

EMIS_PATH   = os.path.join(BASE_DIR, "EMIS_Clasificado_Completo.xlsx")
FISCAL_PATH = os.path.join(ROOT_DIR, "Proceso_Fiscal", "Reporte_Fiscal_Historico.csv")
OUTPUT_PATH = os.path.join(BASE_DIR, "EMIS_Con_Historia_Fiscal.xlsx")
CACHE_PATH  = os.path.join(BASE_DIR, "llm_cache_matching.json")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
SCORE_AUTO  = 90    # > SCORE_AUTO  → match automático
SCORE_LLM   = 50    # entre SCORE_LLM y SCORE_AUTO → cola LLM
AZURE_ENDPOINT   = "https://educontinua-resource.cognitiveservices.azure.com/"
AZURE_DEPLOYMENT = "gpt-4.1-mini"
AZURE_API_VERSION = "2025-01-01-preview"
LLM_MODEL        = AZURE_DEPLOYMENT

LEGAL_SUFFIXES = re.compile(
    r'\b(S\.?A\.?P\.?I\.?|S\.?A\.?B\.?|S\.?A\.?\s+DE\s+C\.?V\.?|S\.?A\.?|'
    r'S\.?R\.?L\.?|S\.?C\.?|A\.?C\.?|I\.?A\.?P\.?|'
    r'LLC|INC|CORP|LTD|GMBH|SAS|SRL|BV|NV|AG)\b\.?',
    re.IGNORECASE
)

STOPWORDS = {
    "DE", "LA", "EL", "LOS", "LAS", "Y", "E", "DEL", "EN",
    "THE", "OF", "AND", "GROUP", "GRUPO",
    "MEXICO", "MEXICANA", "MEXICANO", "MEXICANOS",
}

LLM_SYSTEM = (
    "Eres un experto en resolución de entidades corporativas mexicanas. "
    "Tu única tarea es determinar si dos registros corresponden a la misma empresa "
    "o grupo corporativo. Responde ÚNICAMENTE con JSON válido sin texto adicional."
)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------
def normalize_name(text: str) -> str:
    """Normaliza nombre de empresa: quita acentos, sufijos legales y espacios."""
    if not text or pd.isna(text):
        return ""
    text = str(text)
    text = unicodedata.normalize("NFD", text)
    text = text.encode("ascii", "ignore").decode("utf-8")
    text = text.upper().strip()
    text = LEGAL_SUFFIXES.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_domain(url: str) -> str:
    """Extrae el token de dominio: 'https://www.femsa.com/x' → 'femsa'."""
    if not url or pd.isna(url):
        return ""
    try:
        netloc = urlparse(str(url)).netloc or urlparse("http://" + str(url)).netloc
        netloc = netloc.lower().replace("www.", "")
        domain = netloc.split(".")[0]
        return domain
    except Exception:
        return ""


def tokenize(text: str) -> set:
    """Divide un nombre normalizado en tokens significativos."""
    tokens = set(re.split(r"[\s\-/]+", text))
    tokens = {t for t in tokens if len(t) >= 2 and t not in STOPWORDS}
    return tokens


# ---------------------------------------------------------------------------
# Carga de datos
# ---------------------------------------------------------------------------
def load_sources():
    print("Cargando EMIS...")
    emis = pd.read_excel(EMIS_PATH, sheet_name="NACIONAL", dtype={"D-U-N-S® Number": str})

    print("Cargando Reporte Fiscal Histórico...")
    fiscal = pd.read_csv(FISCAL_PATH, encoding="utf-8-sig", dtype=str)

    # Señales normalizadas EMIS
    emis["_nom"]    = emis["Company Name"].apply(normalize_name)
    emis["_trade"]  = emis["Tradestyle"].apply(normalize_name)
    emis["_parent"] = emis["Parent Company"].apply(normalize_name)
    emis["_global"] = emis["Global Ultimate Company"].apply(normalize_name)
    emis["_domain"] = emis["URL"].apply(extract_domain)

    # Señales normalizadas Fiscal
    fiscal["_homolog"]   = fiscal["NombreHomologado"].apply(normalize_name)
    fiscal["_receptor"]  = fiscal["Nombre del Receptor"].apply(normalize_name)
    fiscal["_name_orig"] = fiscal["Name"].apply(normalize_name)

    return emis, fiscal


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------
def build_index(emis: pd.DataFrame) -> dict:
    """Índice invertido: token → lista de índices de fila EMIS."""
    index = {}
    for row_idx, row in emis.iterrows():
        tokens = tokenize(row["_nom"]) | tokenize(row["_trade"])
        for tok in tokens:
            index.setdefault(tok, []).append(row_idx)
    return index


def get_candidates(fiscal_row: pd.Series, emis_index: dict) -> set:
    """Retorna índices EMIS candidatos por token compartido."""
    tokens = tokenize(fiscal_row["_homolog"]) | tokenize(fiscal_row["_receptor"])
    candidates = set()
    for tok in tokens:
        candidates.update(emis_index.get(tok, []))
    return candidates


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_pair(emis_row: pd.Series, fiscal_row: pd.Series) -> float:
    """Score ponderado multi-señal entre una empresa EMIS y una fiscal."""
    s_nombre = fuzz.WRatio(emis_row["_nom"],    fiscal_row["_homolog"])
    s_trade  = fuzz.WRatio(emis_row["_trade"],  fiscal_row["_receptor"])
    s_parent = fuzz.WRatio(emis_row["_parent"], fiscal_row["_homolog"])

    # URL domain: 100 si coincide, 0 si no
    dom_emis  = emis_row["_domain"]
    dom_fiscal = extract_domain("")  # fiscal no tiene URL — comparar contra nombre
    # Comparar dominio EMIS contra nombre fiscal normalizado
    s_url = 100 if (dom_emis and dom_emis in fiscal_row["_homolog"].lower()) else 0

    score = (
        s_nombre * 0.40 +
        s_trade  * 0.20 +
        s_url    * 0.25 +
        s_parent * 0.15
    )
    return round(score, 2)


# ---------------------------------------------------------------------------
# LLM Judge
# ---------------------------------------------------------------------------
def load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def cache_key(duns: str, id_fiscal: str) -> str:
    return hashlib.sha256(f"{duns}|{id_fiscal}".encode()).hexdigest()[:16]


def _parse_hist(val):
    """Parse JSON {Ultimo, Historico}; tolera valores planos legacy."""
    if val is None or val == "" or (isinstance(val, float) and pd.isna(val)):
        return {"Ultimo": None, "Historico": []}
    if isinstance(val, dict):
        return val
    try:
        obj = json.loads(val)
        if isinstance(obj, dict) and "Ultimo" in obj:
            return obj
    except Exception:
        pass
    return {"Ultimo": str(val), "Historico": [str(val)]}


def _parse_variantes_ids(val):
    """VariantesIdEmpresa: {nombre_variante: IdEmpresa}."""
    if val is None or val == "" or (isinstance(val, float) and pd.isna(val)):
        return {}
    if isinstance(val, dict):
        return val
    try:
        obj = json.loads(val)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


BATCH_SIZE = 10   # pares por llamada LLM — ajustar según tiempos observados


def _build_pair_block(idx: int, emis_row: pd.Series, fiscal_row: pd.Series) -> str:
    return (
        f"PAR {idx}:\n"
        f"  EMIS   - Company Name: \"{emis_row.get('Company Name', '')}\"\n"
        f"         - Tradestyle: \"{emis_row.get('Tradestyle', '')}\"\n"
        f"         - URL: {emis_row.get('URL', '')}\n"
        f"         - Parent: \"{emis_row.get('Parent Company', '')}\"\n"
        f"         - Global Ultimate: \"{emis_row.get('Global Ultimate Company', '')}\"\n"
        f"  FISCAL - NombreHomologado: \"{fiscal_row.get('NombreHomologado', '')}\"\n"
        f"         - Nombre del Receptor: \"{fiscal_row.get('Nombre del Receptor', '')}\"\n"
        f"         - RFC: \"{fiscal_row.get('RFC receptor', '')}\""
    )


def llm_judge_batch(pairs: list, emis: pd.DataFrame, fiscal: pd.DataFrame,
                    cache: dict, client: AzureOpenAI) -> list:
    """
    Evalúa un lote de pares en una sola llamada LLM.
    Retorna lista de {'match': bool, 'razon': str} en el mismo orden.
    Los pares ya en cache se omiten de la llamada y se resuelven localmente.
    """
    import time

    results    = [None] * len(pairs)
    pendientes = []   # índices que necesitan llamada LLM

    # Resolver desde cache los que ya tienen resultado
    for i, pair in enumerate(pairs):
        key = cache_key(pair["duns"], pair["RFC"])
        if key in cache:
            results[i] = cache[key]
        else:
            pendientes.append(i)

    if not pendientes:
        return results

    # Construir prompt con todos los pares pendientes
    bloques = []
    for seq, i in enumerate(pendientes, 1):
        pair  = pairs[i]
        e_row = emis.loc[pair["e_idx"]]
        f_row = fiscal.loc[pair["f_idx"]]
        bloques.append(_build_pair_block(seq, e_row, f_row))

    n = len(pendientes)
    prompt = (
        f"Evalúa los siguientes {n} pares de empresas.\n"
        f"Para cada PAR responde si corresponden a la misma empresa o grupo corporativo.\n\n"
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
            {"role": "user",   "content": prompt},
        ]
    )
    t_fin      = time.time()
    segundos   = t_fin - t_inicio
    tokens_in  = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens
    cached     = getattr(getattr(response.usage, "prompt_tokens_details", None),
                         "cached_tokens", 0) or 0
    pct_cache  = f"{cached/tokens_in*100:.0f}%" if tokens_in else "0%"
    print(f"    Lote {n} pares → {segundos:.1f}s | "
          f"{segundos/n:.2f}s/par | "
          f"tokens: {tokens_in} in ({pct_cache} cacheados) / {tokens_out} out")

    raw = response.choices[0].message.content.strip()

    # Parsear respuesta
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
    except json.JSONDecodeError:
        match_arr = re.search(r'\[.*\]', raw, re.DOTALL)
        try:
            parsed = json.loads(match_arr.group()) if match_arr else []
        except Exception:
            parsed = []

    # Asignar resultados y guardar en cache
    for seq_idx, i in enumerate(pendientes):
        pair = pairs[i]
        key  = cache_key(pair["duns"], pair["RFC"])
        if seq_idx < len(parsed):
            res = {"match": bool(parsed[seq_idx].get("match")),
                   "razon": parsed[seq_idx].get("razon", "")}
        else:
            res = {"match": False, "razon": "parse_error"}
        cache[key]  = res
        results[i]  = res

    save_cache(cache)
    return results


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def run_matching():
    emis, fiscal = load_sources()
    emis_index   = build_index(emis)
    cache        = load_cache()
    client       = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=os.environ[_API_KEY_VAR],
        api_version=AZURE_API_VERSION,
    )

    auto_matches = []   # pares confirmados automáticamente
    llm_queue    = []   # pares ambiguos para LLM

    print(f"\nProcesando {len(fiscal)} registros fiscales contra {len(emis)} empresas EMIS...")

    for f_idx, f_row in fiscal.iterrows():
        candidates = get_candidates(f_row, emis_index)
        if not candidates:
            continue

        # Datos derivados del esquema fiscal nuevo (JSON consolidado por RFC)
        variantes_ids = _parse_variantes_ids(f_row.get("VariantesIdEmpresa", ""))
        ids_crm = list(variantes_ids.values())
        regimen_obj = _parse_hist(f_row.get("RegimenFiscal", ""))
        fecha_obj = _parse_hist(f_row.get("FechaFacturacion", ""))

        for e_idx in candidates:
            e_row = emis.loc[e_idx]
            score = score_pair(e_row, f_row)

            pair = {
                "duns":          str(e_row.get("D-U-N-S® Number", "")),
                "e_idx":         e_idx,
                "f_idx":         f_idx,
                "IdsCRM":        ids_crm,                             # lista de IdEmpresa (Salesforce Account Ids)
                "VariantesIds":  variantes_ids,                       # mapa {variante: IdEmpresa}
                "IdCliente":     str(f_row.get("ID Cliente", "")),
                "RFC":           str(f_row.get("RFC receptor", "")),
                "RegimenFiscal": str(regimen_obj.get("Ultimo") or ""),
                "UltimaFecha":   str(fecha_obj.get("Ultimo") or ""),
                "NombreOrig":    str(f_row.get("Name", "")),
                "NombreHom":     str(f_row.get("NombreHomologado", "")),
                "NombreRec":     str(f_row.get("Nombre del Receptor", "")),
                "score":         score,
                "fuente":        "auto",
            }

            if score > SCORE_AUTO:
                auto_matches.append(pair)
            elif score >= SCORE_LLM:
                llm_queue.append(pair)

    print(f"  Auto-matches: {len(auto_matches)}")
    print(f"  Cola LLM:     {len(llm_queue)}")

    # --- LLM Judge (agrupado por empresa EMIS) ---
    # Agrupar cola por D-U-N-S (e_idx)
    from collections import defaultdict
    grupos = defaultdict(list)
    for pair in llm_queue:
        grupos[pair["e_idx"]].append(pair)

    llm_matches = []
    total_grupos = len(grupos)
    print(f"\nEvaluando {len(llm_queue)} pares agrupados en {total_grupos} empresas EMIS...\n")

    for g_num, (e_idx, pares) in enumerate(grupos.items(), 1):
        e_row     = emis.loc[e_idx]
        emis_name = str(e_row.get("Company Name", ""))

        # Procesar pares del grupo en lotes de BATCH_SIZE
        resultados_grupo = []
        for lote_inicio in range(0, len(pares), BATCH_SIZE):
            lote  = pares[lote_inicio: lote_inicio + BATCH_SIZE]
            resps = llm_judge_batch(lote, emis, fiscal, cache, client)
            for pair, result in zip(lote, resps):
                if result is None:
                    result = {"match": False, "razon": "sin_respuesta"}
                match = result.get("match", False)
                razon = result.get("razon", "")
                f_row = fiscal.loc[pair["f_idx"]]
                resultados_grupo.append({
                    "match":     match,
                    "razon":     razon,
                    "fisc_name": str(f_row.get("NombreHomologado", ""))[:50],
                    "rfc":       str(f_row.get("RFC receptor", "")),
                    "score":     pair["score"],
                    "pair":      pair,
                })
                if match:
                    pair["fuente"]    = "llm"
                    pair["llm_razon"] = razon
                    llm_matches.append(pair)

        # Mostrar solo empresas EMIS con al menos un match confirmado
        confirmados = [r for r in resultados_grupo if r["match"]]
        if confirmados:
            print(f"{'═'*60}")
            print(f"[{g_num}/{total_grupos}] EMIS: {emis_name}")
            print(f"{'─'*60}")
            for r in resultados_grupo:
                icono = "✔ MATCH" if r["match"] else "✘"
                print(f"  {icono:<8} Score:{r['score']:5.1f}  Fiscal: {r['fisc_name']}")
                if r["match"]:
                    print(f"           RFC   : {r['rfc']}")
                    print(f"           Razón : {r['razon']}")
            print()

    all_matches = auto_matches + llm_matches
    print(f"\nTotal matches confirmados: {len(all_matches)}")

    # --- Diagnóstico: registros fiscales sin match ---
    matched_f_idx = {m["f_idx"] for m in all_matches}
    sin_match = fiscal[~fiscal.index.isin(matched_f_idx)]
    if not sin_match.empty:
        print(f"\n{'─'*60}")
        print(f"REGISTROS FISCALES SIN MATCH ({len(sin_match)}):")
        print(f"{'─'*60}")
        for _, row in sin_match.iterrows():
            print(f"  • {row.get('NombreHomologado','')[:50]}  |  RFC: {row.get('RFC receptor','')}")
        print(f"{'─'*60}\n")

    # --- Ensamblado por DUNS ---
    resultado = build_result(emis, all_matches)
    export_output(resultado, all_matches)
    print(f"\nSalida guardada en: {OUTPUT_PATH}")


def load_to_etl(origen: str):
    """
    Paso 3: TRUNCATE + INSERT del Excel resultado a [ETL].[dbo].[Reporte_RelacionEMIS].

    Foto del último estado del pipeline (no acumula histórico). Se ejecuta al
    cierre de cada corrida (Diario o Semanal) para que la BD ETL refleje el
    Excel actual.

    Mapeo Excel → SQL:
        D-U-N-S® Number    → DUNS_Number
        Company Name       → Company_Name
        Facturado          → Facturado (BIT)
        Revisado_CRM       → Revisado_CRM (BIT)
        Detalle_Matches    → Detalle_Matches (NVARCHAR(MAX))
        Ultima_Facturacion → Ultima_Facturacion ("" → NULL)
        Score_Max          → Score_Max (NaN → NULL)
        Fuente_Match       → Fuente_Match
        Fecha_Carga        → autogenerado por DEFAULT GETDATE() en SQL.

    Sigue el patrón de U4O_Limpieza_Fiscal.py:361-376 (TRUNCATE + executemany).
    """
    import sys as _sys
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _root not in _sys.path:
        _sys.path.append(_root)
    import Conexiones

    print(f"Leyendo {os.path.basename(OUTPUT_PATH)} para cargar a SQL...")
    df = pd.read_excel(
        OUTPUT_PATH,
        sheet_name="Matches_Detalle",
        dtype={"D-U-N-S® Number": str},
    )

    # Renombrar columnas Excel → SQL (las únicas con caracteres no-SQL-safe)
    df = df.rename(columns={
        "D-U-N-S® Number": "DUNS_Number",
        "Company Name":    "Company_Name",
    })

    insert_cols = [
        "DUNS_Number", "Company_Name", "Facturado", "Revisado_CRM",
        "Detalle_Matches", "Ultima_Facturacion", "Score_Max", "Fuente_Match",
    ]

    def _normalize(v):
        """NaN → None; "" → None; bool/float/str → mismo tipo."""
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v if v != "" else None
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        return v

    rows = [tuple(_normalize(v) for v in row)
            for row in df[insert_cols].itertuples(index=False, name=None)]
    total = len(rows)

    print(f"Conectando a [ETL] (origen='{origen}')...")
    conn, cursor = Conexiones.connect_ETL_local_sql(origen)
    if conn is None:
        raise RuntimeError(
            f"connect_ETL_local_sql('{origen}') retornó None. "
            f"Origen válido: 'Erik' o 'Antonio'."
        )

    try:
        # Detalle_Matches es NVARCHAR(MAX) — mismo patrón que en
        # U4O_Centralizar_ETL.py:44 para Reporte_FiscalHistorico.
        cursor.fast_executemany = False

        cursor.execute("TRUNCATE TABLE [dbo].[Reporte_RelacionEMIS]")
        print("  TRUNCATE [dbo].[Reporte_RelacionEMIS] ejecutado.")

        col_list_sql = ", ".join(f"[{c}]" for c in insert_cols)
        placeholders = ", ".join(["?"] * len(insert_cols))
        sql = (f"INSERT INTO [dbo].[Reporte_RelacionEMIS] "
               f"({col_list_sql}) VALUES ({placeholders})")

        # Insert por lotes de 1000 con feedback
        batch_size = 1000
        for i in range(0, total, batch_size):
            batch = rows[i:i + batch_size]
            cursor.executemany(sql, batch)
            print(f"  Insertadas {min(i + batch_size, total):,}/{total:,} filas")
        conn.commit()
        print(f"✓ [ETL].[dbo].[Reporte_RelacionEMIS] actualizada con {total:,} filas.")
    except Exception as e:
        print(f"⚠ Error cargando a SQL — se intenta rollback: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        cursor.close()
        conn.close()


def run_full_pipeline(origen: str, skip_crm: bool = False, refresh_crm: bool = False,
                      skip_etl: bool = False):
    """
    Ejecuta los 3 pasos del pipeline EMIS:
      1. Matching fiscal (run_matching).
      2. Sub-proceso CRM (run_crm_subprocess).
      3. Carga del Excel resultado a [ETL].[dbo].[Reporte_RelacionEMIS] (load_to_etl).

    Flags:
      skip_crm=True    → omite Paso 2 (solo matching fiscal).
      refresh_crm=True → en Paso 2, revalida los Facturado=False contra el
                         catálogo CRM (uso semanal).
      skip_etl=True    → omite Paso 3 (no toca SQL). Útil para QA local.
    """
    print("=" * 70)
    print("PASO 1: Matching EMIS ↔ Historia Fiscal")
    print("=" * 70)
    run_matching()

    if skip_crm:
        print("\n--skip-crm activo: se omite Paso 2 (sub-proceso CRM).")
    else:
        print()
        print("=" * 70)
        print("PASO 2: Enriquecimiento CRM para EMIS sin facturación")
        if refresh_crm:
            print("(modo refresh: revalidando todos los Facturado=False contra el catálogo CRM actual)")
        print("=" * 70)
        # Import compatible con dos formas de invocación:
        #   - Standalone (desde Procesos_Matching_EMIS/): import simple por nombre.
        #   - Como paquete (importado desde la raíz, p.ej. CierresU4O_Proceso01.py):
        #     import absoluto con prefijo del paquete.
        try:
            from U4O_Matching_EMIS_SinFactura import run_crm_subprocess
        except ModuleNotFoundError:
            from Procesos_Matching_EMIS.U4O_Matching_EMIS_SinFactura import run_crm_subprocess
        run_crm_subprocess(origen=origen, refresh_crm=refresh_crm)

    if skip_etl:
        print("\n--skip-etl activo: se omite Paso 3 (carga a SQL).")
        return

    print()
    print("=" * 70)
    print("PASO 3: Carga a [ETL].[dbo].[Reporte_RelacionEMIS]")
    print("=" * 70)
    try:
        load_to_etl(origen)
    except Exception as e:
        print(f"⚠ Paso 3 falló: {e}\n  El Excel quedó OK; reintenta la carga después con --skip-crm.")
        # No re-raise: el pipeline ya hizo el trabajo principal (Excel actualizado).


def build_result(emis: pd.DataFrame, all_matches: list) -> pd.DataFrame:
    """Agrega matches por DUNS y hace left join al DataFrame EMIS."""
    from collections import defaultdict

    agg = defaultdict(lambda: {
        "IdsCRM":           [],
        "IdsCliente":       [],
        "RFCs_Asociados":   [],
        "Regimenes_Fiscales": [],
        "Variantes_Nombre": [],
        "Fechas":           [],
        "Scores":           [],
        "Fuentes":          [],
        "Razones_LLM":      [],
    })

    for m in all_matches:
        d = agg[m["duns"]]
        for _id in m.get("IdsCRM", []):
            _append_unique(d["IdsCRM"], _id)
        _append_unique(d["IdsCliente"],         m["IdCliente"])
        _append_unique(d["RFCs_Asociados"],     m["RFC"])
        _append_unique(d["Regimenes_Fiscales"], m["RegimenFiscal"])
        for v in [m["NombreOrig"], m["NombreHom"], m["NombreRec"]]:
            _append_unique(d["Variantes_Nombre"], v)
        d["Fechas"].append(m["UltimaFecha"])
        d["Scores"].append(m["score"])
        d["Fuentes"].append(m["fuente"])
        if m.get("llm_razon"):
            _append_unique(d["Razones_LLM"], m["llm_razon"])

    rows = []
    for _, e_row in emis.iterrows():
        duns = str(e_row.get("D-U-N-S® Number", ""))
        d    = agg.get(duns, {})
        facturado = bool(d)

        rows.append({
            "Facturado":          facturado,
            "Revisado_CRM":       facturado,  # ya facturó → no requiere lookup en CRM sin-factura
            "IdsCRM":             json.dumps(d.get("IdsCRM", []),            ensure_ascii=False),
            "IdsCliente":         json.dumps(d.get("IdsCliente", []),        ensure_ascii=False),
            "RFCs_Asociados":     json.dumps(d.get("RFCs_Asociados", []),    ensure_ascii=False),
            "Regimenes_Fiscales": json.dumps(d.get("Regimenes_Fiscales", []),ensure_ascii=False),
            "Variantes_Nombre":   json.dumps(d.get("Variantes_Nombre", []),  ensure_ascii=False),
            "Scores":             json.dumps(d.get("Scores", []),            ensure_ascii=False),
            "Ultima_Facturacion": max(d["Fechas"]) if d.get("Fechas") else "",
            "Score_Max":          max(d["Scores"]) if d.get("Scores") else 0.0,
            "Fuente_Match":       _resolve_fuente(d.get("Fuentes", [])),
            "Razones_LLM":        json.dumps(d.get("Razones_LLM", []),       ensure_ascii=False),
        })

    result_df = pd.concat([emis.reset_index(drop=True),
                           pd.DataFrame(rows)], axis=1)
    # Eliminar columnas internas de normalización
    result_df.drop(columns=[c for c in result_df.columns if c.startswith("_")],
                   inplace=True)
    return result_df


def export_output(resultado: pd.DataFrame, all_matches: list):
    """Exporta el Excel: una fila por DUNS con un solo JSON consolidado de variantes.

    Preserva el progreso del Paso 2 entre corridas: si existe un Excel previo,
    para cada DUNS con Facturado=False que ya tenía Revisado_CRM=True hereda
    Revisado_CRM, Score_Max, Fuente_Match (si crm_sin_factura_*) y los campos
    IdsCRM/Variantes_Nombre/Razones_LLM dentro de Detalle_Matches.
    """
    campos_json = [
        "IdsCRM", "IdsCliente", "RFCs_Asociados",
        "Regimenes_Fiscales", "Variantes_Nombre", "Razones_LLM",
    ]

    def _consolidar(row):
        obj = {}
        for c in campos_json:
            val = row.get(c, "[]")
            try:
                obj[c] = json.loads(val) if isinstance(val, str) else val
            except Exception:
                obj[c] = []
        return json.dumps(obj, ensure_ascii=False)

    resultado = resultado.copy()
    resultado["Detalle_Matches"] = resultado.apply(_consolidar, axis=1)

    columnas_salida = [
        "D-U-N-S® Number",
        "Company Name",
        "Facturado",
        "Revisado_CRM",
        "Detalle_Matches",
        "Ultima_Facturacion",
        "Score_Max",
        "Fuente_Match",
    ]
    salida = resultado[[c for c in columnas_salida if c in resultado.columns]].copy()

    # === Preservar progreso del Paso 2 ===
    if os.path.exists(OUTPUT_PATH):
        try:
            prev = pd.read_excel(OUTPUT_PATH, sheet_name="Matches_Detalle",
                                 dtype={"D-U-N-S® Number": str})
            if "Revisado_CRM" in prev.columns:
                prev_by_duns = {str(r["D-U-N-S® Number"]): r for _, r in prev.iterrows()}
                heredados = 0
                for idx, row in salida.iterrows():
                    if bool(row["Facturado"]):
                        continue  # facturado → datos vienen del Paso 1, no heredar
                    duns = str(row["D-U-N-S® Number"])
                    prev_row = prev_by_duns.get(duns)
                    if prev_row is None or not bool(prev_row.get("Revisado_CRM", False)):
                        continue
                    salida.at[idx, "Revisado_CRM"] = True
                    sm_prev = prev_row.get("Score_Max")
                    if pd.notna(sm_prev):
                        salida.at[idx, "Score_Max"] = float(sm_prev)
                    fm_prev = str(prev_row.get("Fuente_Match", ""))
                    if fm_prev.startswith("crm_sin_factura"):
                        salida.at[idx, "Fuente_Match"] = fm_prev
                    try:
                        obj_new = json.loads(row["Detalle_Matches"]) if isinstance(row["Detalle_Matches"], str) else {}
                        obj_prev = json.loads(prev_row["Detalle_Matches"]) if isinstance(prev_row["Detalle_Matches"], str) else {}
                        for k in ("IdsCRM", "Variantes_Nombre", "Razones_LLM"):
                            if obj_prev.get(k):
                                obj_new[k] = obj_prev[k]
                        salida.at[idx, "Detalle_Matches"] = json.dumps(obj_new, ensure_ascii=False)
                    except Exception:
                        pass
                    heredados += 1
                print(f"  Progreso Paso 2 heredado del Excel previo: {heredados} DUNS.")
        except Exception as e:
            print(f"  AVISO: no se pudo leer Excel previo para preservar progreso: {e}")

    # Escritura atómica: escribir a *.tmp.xlsx y os.replace — si el proceso muere
    # a media escritura, el Excel original previo no queda corrupto.
    # NOTA: pandas valida que la extensión sea .xlsx, por eso queda *.tmp.xlsx.
    _root, _ext = os.path.splitext(OUTPUT_PATH)
    tmp_path = f"{_root}.tmp{_ext}"
    try:
        with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
            salida.to_excel(writer, sheet_name="Matches_Detalle", index=False)
        os.replace(tmp_path, OUTPUT_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _append_unique(lst: list, value: str):
    value = value.strip()
    if value and value not in lst:
        lst.append(value)


def _resolve_fuente(fuentes: list) -> str:
    if not fuentes:
        return "sin_match"
    if "llm" in fuentes:
        return "llm"
    return "auto"


# ---------------------------------------------------------------------------
def main(origen, periodo):
    """
    Punto de entrada único (programático y CLI). Invocado por el orquestador
    CierresU4O_Proceso01.py como run_main_25(origen, periodo).

    Comportamiento según `periodo`:
      - "Diario"  : Paso 1 + Paso 2 (solo pendientes Revisado_CRM=False) + Paso 3 carga a SQL.
      - "Semanal" : Paso 1 + Paso 2 con refresh (revalida Facturado=False vs catálogo CRM) + Paso 3.
      - cualquier otro valor → se trata como "Diario".

    Siempre ejecuta el Paso 3 (TRUNCATE + INSERT a [ETL].[dbo].[Reporte_RelacionEMIS]).
    Para omitirlo en QA local usar el CLI con --skip-etl.
    """
    refresh_crm = (str(periodo).strip().lower() == "semanal")
    run_full_pipeline(origen=origen, skip_crm=False, refresh_crm=refresh_crm, skip_etl=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Pipeline EMIS-Fiscal (Paso 1) + CRM (Paso 2) + Carga ETL (Paso 3)."
    )
    parser.add_argument("--origen", type=str, required=True,
                        help="'Erik' o 'Antonio' para connect_ETL_local_sql.")
    parser.add_argument("--periodo", type=str, default="Diario",
                        choices=["Diario", "Semanal"],
                        help="Diario: solo procesa pendientes. Semanal: revalida todos "
                             "los Facturado=False contra el catálogo CRM actual.")
    parser.add_argument("--skip-crm", action="store_true",
                        help="Omite Paso 2 (sub-proceso CRM).")
    parser.add_argument("--skip-etl", action="store_true",
                        help="Omite Paso 3 (carga a [ETL].[dbo].[Reporte_RelacionEMIS]).")
    args = parser.parse_args()
    refresh_crm = (args.periodo.strip().lower() == "semanal")
    run_full_pipeline(origen=args.origen, skip_crm=args.skip_crm,
                      refresh_crm=refresh_crm, skip_etl=args.skip_etl)
