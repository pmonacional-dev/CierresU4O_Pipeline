# Manual del proceso EMIS ↔ Historia Fiscal + CRM

Documentación funcional y de reglas de negocio del pipeline de matching EMIS.

## 1. Visión general

El proceso enriquece el catálogo EMIS (~9,100 empresas mexicanas con D-U-N-S®) con dos fuentes:

1. **Historia Fiscal** — empresas que han emitido facturas a U4O. Vive en `Reporte_Fiscal_Historico.csv` (lo genera `Proceso_Fiscal/U4O_Limpieza_Fiscal.py`).
2. **CRM (Salesforce)** — todas las cuentas U4O en SF, hayan facturado o no. Vive en SQL Server local: `[ETL].[dbo].[Extraer_EmpresasU4O]` + `[ETL].[dbo].[EmpresasHomologadas]`.

El pipeline produce un único Excel: `EMIS_Con_Historia_Fiscal.xlsx`, con una fila por DUNS y un JSON consolidado `Detalle_Matches` que reúne todos los identificadores asociados.

**Por qué dos fuentes:** una empresa puede existir en el CRM sin haber facturado nunca (lead/oportunidad activa), o haber facturado pero estar registrada en SF con varias variantes de nombre. Combinar ambas fuentes maximiza cobertura.

## 2. Arquitectura: 2 pasos secuenciales

### Paso 1 — Matching EMIS ↔ Historia Fiscal

**Archivo:** `U4O_Matching_EMIS_Fiscal.py` — función `run_matching()`.

**Input:**
- `EMIS_Clasificado_Completo.xlsx` (hoja NACIONAL, 9,106 filas, columnas D-U-N-S®, Company Name, Tradestyle, URL, Parent, Global Ultimate, etc.).
- `Reporte_Fiscal_Historico.csv` (~775 filas — solo empresas que facturaron).

**Algoritmo:**
1. Normaliza nombres (NFD → ASCII, mayúsculas, quita sufijos legales: `S.A.`, `S.A. de C.V.`, `LLC`, etc., colapsa espacios).
2. Tokeniza (split por espacio/guion/slash, descarta tokens < 2 chars y stopwords: `DE`, `LA`, `EL`, `MEXICO`, `GROUP`, etc.).
3. **Blocking** por índice invertido `token → [filas EMIS]` para reducir candidatos.
4. **Scoring multi-señal** entre EMIS y fila fiscal:
   - 40% `WRatio(Company Name, NombreHomologado)`
   - 20% `WRatio(Tradestyle, Nombre del Receptor)`
   - 25% `dominio URL ∈ NombreHomologado` (binario 0/100)
   - 15% `WRatio(Parent Company, NombreHomologado)`
5. **Decisión:**
   - score > 90 → match automático.
   - 50 ≤ score ≤ 90 → cola LLM.
   - score < 50 → descarte.
6. **LLM judge** (Azure GPT-4.1 mini, `gpt-4.1-mini`) para resolver casos ambiguos: agrupa pares por DUNS, los manda en lotes de 10. Cache: `llm_cache_matching.json` con clave `sha256(DUNS|RFC)[:16]` para no re-pagar tokens.

**Output:** sobrescribe `EMIS_Con_Historia_Fiscal.xlsx`. Cada DUNS recibe:
- `Facturado` (bool)
- `Detalle_Matches` (JSON — ver sección 4)
- `Score_Max`, `Ultima_Facturacion`, `Fuente_Match`, `Revisado_CRM`

### Paso 2 — Sub-proceso CRM para EMIS sin facturación

**Archivo:** `U4O_Matching_EMIS_SinFactura.py` — función `run_crm_subprocess(...)`.

**Input:**
- El Excel resultado del Paso 1 (lee filas con `Facturado=False`).
- Catálogo CRM construido al vuelo desde `[ETL].[dbo].[Extraer_EmpresasU4O]` y `[ETL].[dbo].[EmpresasHomologadas]`.

**Construcción del catálogo CRM (`build_crm_catalog`):**
1. Lee TODAS las cuentas SF (no se filtra por `VEC_ID_Empresa__c` — buscamos variantes de Account Id, no de VEC).
2. Lee mapeo `NombreOriginal ↔ NombrePrincipal` de `EmpresasHomologadas`.
3. Agrupa por `NombrePrincipal` con sus variantes (NombreOriginal + el principal mismo).
4. Cobertura adicional: cuentas SF que no aparecen en homologadas se agregan como "principal sintético" (nombre = nombre original).
5. Para cada `NombrePrincipal` resuelve `IdsCRM`: lookup `Name_upper → Id_SF`. Lookup es `dict[Name, list[Ids]]` para preservar todos los Ids cuando dos cuentas comparten Name.
6. Resultado: DataFrame con `NombrePrincipal`, `Variantes`, `IdsCRM`, tokens normalizados.

**Algoritmo de matching CRM:**
1. Mismo `normalize_name` y `tokenize` que Paso 1.
2. Blocking sobre tokens del EMIS (Company Name + Tradestyle + Parent).
3. **Scoring CRM** distinto al fiscal (porque CRM no tiene URL/Tradestyle propios):
   - 55% `max(WRatio(Company Name, NombrePrincipal), max WRatio(Company Name, variante))` — best-of contra principal y todas las variantes.
   - 20% `max WRatio(Tradestyle, variante)`.
   - 15% `dominio URL ∈ NombrePrincipal` (binario).
   - 10% `WRatio(Parent, NombrePrincipal)`.
4. Decisión auto/LLM/descarte con los mismos umbrales 50/90 que Paso 1.
5. LLM judge con prompt adaptado (`_build_pair_block_crm`): muestra `NombrePrincipal`, primeras 5 variantes, count de `IdsCRM`. Cache separado: `llm_cache_test_crm.json` con clave `sha256(DUNS|NombrePrincipal)[:16]` (cachea por grupo corporativo, no por cada Id).

**Output:** in-place sobre `EMIS_Con_Historia_Fiscal.xlsx`:
- Si hay match: actualiza `Detalle_Matches.IdsCRM`, `Detalle_Matches.Variantes_Nombre`, `Detalle_Matches.Razones_LLM`, `Score_Max`, `Fuente_Match` (con prefijo `crm_sin_factura_*`).
- Marca `Revisado_CRM=True` para no reprocesar en corridas Diarias siguientes.
- `Facturado` queda en `False` (no facturó); `IdsCliente`/`RFCs_Asociados`/`Regimenes_Fiscales` quedan vacíos por definición.

## 3. Modos Diario vs Semanal

Controlado por `periodo` desde el orquestador `CierresU4O_Proceso01.py:111` (también vía CLI `--periodo`).

### Diario

- **Paso 1**: full re-match (regenera todo el Excel).
- **Paso 2**: solo procesa DUNS con `Facturado=False AND Revisado_CRM=False`. Los ya marcados quedan congelados.
- **Tiempo típico** una vez alcanzado estado estable: segundos.

**Cuándo usar:** todos los días para capturar:
- Empresas EMIS que pasaron de no-facturado a facturado por una factura nueva.
- Pendientes nuevos que aún no se hayan revisado.

### Semanal (refresh)

- **Paso 1**: igual.
- **Paso 2 con refresh selectivo**: detecta qué cambió en el catálogo CRM desde la última corrida, resetea `Revisado_CRM=False` solo para los DUNS afectados, los reprocesa.

**Cómo detecta los cambios** (`compute_catalog_signature`):
1. Para cada `NombrePrincipal` calcula `hash16(IdsCRM_sorted ∪ Variantes_normalizadas_sorted)`.
2. Persiste `crm_catalog_signature.json` con dict `{NombrePrincipal: hash}` + `{variante_upper: NombrePrincipal}`.
3. En la siguiente corrida compara firma actual vs previa:
   - `modificados`: mismo `NombrePrincipal`, hash distinto (cambió IdsCRM o variantes).
   - `nuevos`: aparecen en SF pero no estaban antes.
   - `eliminados`: estaban antes, ya no están.
4. **DUNS afectados:**
   - Con match (`IdsCRM ≠ []`): se reprocesa si alguna `Variantes_Nombre` mapea a un `NombrePrincipal` modificado/eliminado (vía firma previa).
   - Sin match: se reprocesan TODOS, pero solo si hay principales nuevos (porque ahora podrían encontrar match). Si solo hubo modificaciones, los sin_match no se tocan.

**Caso especial — primera corrida Semanal en un equipo nuevo:** no existe `crm_catalog_signature.json`. Cae en **fallback masivo** (resetea todos los `Facturado=False`) y crea la firma. La SIGUIENTE corrida ya hace diff selectivo.

**Cuándo usar:** una vez por semana (típicamente lunes), o cuando sospechas que el catálogo de SF cambió bastante.

### Forzar fallback masivo manualmente

Borrar `Procesos_Matching_EMIS/crm_catalog_signature.json` y correr en modo Semanal. Útil después de una migración o cuando la firma quedó desincronizada.

## 4. Esquema de salida — `EMIS_Con_Historia_Fiscal.xlsx`

Hoja `Matches_Detalle`. Columnas:

| Columna | Tipo | Significado |
|---|---|---|
| `D-U-N-S® Number` | str | Identificador único EMIS |
| `Company Name` | str | Razón social del catálogo EMIS |
| `Facturado` | bool | True si Paso 1 encontró al menos una factura |
| `Revisado_CRM` | bool | True si el DUNS ya pasó por el sub-proceso CRM (o si `Facturado=True`, que implícitamente lo da por revisado) |
| `Detalle_Matches` | str (JSON) | Objeto consolidado con todos los identificadores — ver abajo |
| `Ultima_Facturacion` | str ISO o "" | Fecha máxima entre todas las facturas asociadas |
| `Score_Max` | float | Score máximo del match ganador (escala 0–100) |
| `Fuente_Match` | str | Categoría — ver sección 5 |

### Estructura de `Detalle_Matches`

```json
{
  "IdsCRM": ["0014100001..."],          // Salesforce Account Ids
  "IdsCliente": ["Q01D53000"],          // ID Cliente del histórico fiscal
  "RFCs_Asociados": ["ADU800131T10"],
  "Regimenes_Fiscales": ["601"],        // Último régimen reportado por RFC
  "Variantes_Nombre": [...],            // Todas las formas en que aparece la empresa
  "Razones_LLM": [...]                  // Justificaciones del LLM si aplicó
}
```

**Por qué un único JSON** (en vez de columnas separadas): facilita la deduplicación entre matches del mismo DUNS y mantiene el Excel angosto. Para análisis se puede explotar con `json.loads`.

## 5. Clasificaciones de `Fuente_Match`

Hay dos familias según de qué Paso vino el match.

### Paso 1 — Match contra historia fiscal (empresa SÍ facturó)

| Valor | Cuándo |
|---|---|
| `auto` | Score ponderado > 90; sin LLM. Match casi literal entre EMIS y nombre fiscal |
| `llm` | Score 50–90 enviado al LLM judge; el modelo confirmó que son la misma empresa o grupo corporativo. Si en el grupo hubo ≥1 LLM positivo, toda la fila se marca `llm` |

### Paso 2 — Match contra catálogo CRM (empresa NO facturó)

`IdsCliente`/`RFCs_Asociados`/`Regimenes_Fiscales` siempre vacíos en estos casos.

| Valor | Cuándo |
|---|---|
| `crm_sin_factura_auto` | Todos los matches confirmados pasaron por score > 90 (alineación literal entre EMIS y `NombrePrincipal`/variante) |
| `crm_sin_factura_llm` | Todos los matches vinieron del LLM judge (50–90 + el modelo dijo "match=true") |
| `crm_sin_factura_mixto` | Un DUNS conectó con varios `NombresPrincipales`: unos por score alto y otros por LLM |

### Sin match

| Valor | Cuándo |
|---|---|
| `sin_match` | El DUNS pasó por el flujo (Paso 1 y Paso 2) y no encontró match. Causas típicas: nombre EMIS muy específico sin tokens compartidos (blocking devuelve 0 candidatos), o todos los candidatos quedaron descartados con score < 50, o el LLM dijo que ninguno era match |

### Lectura práctica para filtrar el Excel

| Para ver... | Filtra `Fuente_Match` por |
|---|---|
| Cuentas conocidas con factura | `auto`, `llm` |
| Cuentas en CRM pero sin factura | `crm_sin_factura_auto`, `crm_sin_factura_llm`, `crm_sin_factura_mixto` |
| EMIS aún no asociados a ningún registro | `sin_match` |

## 6. Reglas de negocio y decisiones de diseño

### Por qué el matching es por nombre y no por RFC

El RFC se almacena en `RFCs_Asociados` pero NO entra al scoring. Razón: solo ~510 EMIS tienen factura (5.6%); de los 8,600 restantes ningún RFC fiscal aplica. Forzar match por RFC limitaría la cobertura al subset facturado. La similitud de nombre + URL + parent funciona como matching universal.

### Por qué dos pasos en lugar de uno

- Paso 1 corre rápido (775 filas fiscales × 9,106 EMIS, blocking lo reduce a ~10K comparaciones).
- Paso 2 usa un catálogo más grande (~5K principales) y aplica el diff de firma para no recorrer todo en cada Diario. Si fuera un solo paso, cada corrida trataría todo igual y se perdería la optimización de "ya revisé esto".

### Por qué la columna `Revisado_CRM`

Sin ella, cada corrida Diaria reprocesaría los 8,600 no-facturados, gastando ~40 min y tokens LLM. Con ella, solo procesa los pendientes acumulados (típicamente <50 una vez en estado estable).

### Por qué el LLM judge en lugar de aceptar todo el blocking + scoring

- Score 50–70: muchos falsos positivos por nombres que comparten una palabra ruidosa (ej. "México", "Servicios"). El blocking puede meter empresas no relacionadas en candidatos.
- Score 70–90: muchos casos legítimos pero con suficiente diferencia textual como para no aceptar a ciegas (ej. "Furukawa México" vs "Furukawa Automotive Systems Mexico" — son la misma empresa? El LLM lo evalúa por contexto corporativo, no solo por edit distance).
- Cache LLM hace que el costo de revisar el mismo par dos veces sea cero.

### Por qué `IdsCRM` es lista en lugar de un solo Id

Una empresa puede tener varias cuentas Salesforce (subsidiarias, históricos sin merge, registros duplicados). Persistir todas ayuda a CRM downstream a saber qué cuentas vinculan al mismo DUNS.

### Por qué se preserva el progreso del Paso 2 cuando el Paso 1 reescribe

`export_output` lee el Excel previo y, para cada `Facturado=False` que ya tenía `Revisado_CRM=True`, hereda:
- `Revisado_CRM=True`
- `Score_Max`, `Fuente_Match` si era `crm_sin_factura_*`
- `Detalle_Matches.IdsCRM/Variantes_Nombre/Razones_LLM`

Sin eso, cada corrida reseteaba el progreso del Paso 2 (caso real que se vio en producción).

### Por qué atomic write (`*.tmp.xlsx` + `os.replace`)

Sin atomic, una interrupción a media escritura del Excel deja un archivo corrupto ("Bad magic number"). La próxima corrida no podía leerlo y el progreso se perdía. Con atomic, o tienes el archivo viejo o el nuevo — nunca uno parcial.

### Por qué el sub-proceso CRM ignora `VEC_ID_Empresa__c`

Originalmente la query filtraba `WHERE VEC_ID_Empresa__c IS NOT NULL` (heredado de `U4O_Limpieza_Fiscal`). Pero eso excluía cuentas SF reales que sí queremos como `IdsCRM` (caso real: "Furukawa Automotive Systems Mexico" tenía VEC=NULL pero es la misma empresa que la EMIS). El sub-proceso busca **variantes de Account Id**, no IdsVEC, así que el filtro se quitó.

### Por qué `name_to_ids_global` es `dict[Name, list[Id]]`

Dos cuentas SF distintas pueden tener el mismo `Name` (case-insensitive). Si fuera `dict[Name, Id]` con `if not in dict`, solo se preservaría la primera cuenta y se perderían IdsCRM legítimos. La lista garantiza que todas las cuentas con ese nombre se incluyan.

## 7. Cómo invocar

### Desde el orquestador

`CierresU4O_Proceso01.py:82`:
```python
run_main_25(origen, periodo)
```
donde `periodo ∈ {"Diario", "Semanal"}` se define en línea 111.

### CLI standalone — pipeline completo (Paso 1 + Paso 2)

```powershell
.\venv\Scripts\python.exe Procesos_Matching_EMIS\U4O_Matching_EMIS_Fiscal.py --origen Erik
.\venv\Scripts\python.exe Procesos_Matching_EMIS\U4O_Matching_EMIS_Fiscal.py --origen Erik --periodo Semanal
.\venv\Scripts\python.exe Procesos_Matching_EMIS\U4O_Matching_EMIS_Fiscal.py --origen Erik --skip-crm    # solo Paso 1
```

### CLI standalone — solo Paso 2 (útil para QA o re-corridas puntuales)

```powershell
# Procesa todos los pendientes (Diario)
.\venv\Scripts\python.exe Procesos_Matching_EMIS\U4O_Matching_EMIS_SinFactura.py --origen Erik

# Procesa los primeros N para QA rápido
.\venv\Scripts\python.exe Procesos_Matching_EMIS\U4O_Matching_EMIS_SinFactura.py --origen Erik --n 50

# Un DUNS específico (ignora Revisado_CRM)
.\venv\Scripts\python.exe Procesos_Matching_EMIS\U4O_Matching_EMIS_SinFactura.py --origen Erik --duns 812250769

# Refresh selectivo manual
.\venv\Scripts\python.exe Procesos_Matching_EMIS\U4O_Matching_EMIS_SinFactura.py --origen Erik --refresh-crm

# Dry run — no escribe Excel ni marca Revisado_CRM
.\venv\Scripts\python.exe Procesos_Matching_EMIS\U4O_Matching_EMIS_SinFactura.py --origen Erik --no-mark
```

### Auditoría puntual

`Audit_CRM_Match.py`: dado un término, muestra qué hay en `Extraer_EmpresasU4O` y `EmpresasHomologadas`, y reproduce la lógica de construcción del grupo CRM para ese término.

```powershell
.\venv\Scripts\python.exe Procesos_Matching_EMIS\Audit_CRM_Match.py --origen Erik --term Furukawa
```

## 8. Archivos persistentes

| Archivo | Propósito | Borrarlo causa... |
|---|---|---|
| `EMIS_Con_Historia_Fiscal.xlsx` | Resultado del pipeline | El próximo Paso 1 lo regenera; se pierde el progreso del Paso 2 |
| `llm_cache_matching.json` | Cache LLM del Paso 1 | Re-llamadas al modelo por cada par del Paso 1 |
| `llm_cache_test_crm.json` | Cache LLM del Paso 2 | Re-llamadas al modelo por cada par del Paso 2 (costoso: ~7.5MB de decisiones) |
| `crm_catalog_signature.json` | Firma del catálogo CRM para diff selectivo | Próximo Semanal cae en fallback masivo |

## 9. Troubleshooting

### "Bad magic number" al leer el Excel

Excel previo corrupto por una corrida interrumpida antes de que se completara la escritura no atómica. Solución: ya no debería pasar (atomic write), pero si llega a ocurrir borra el `.xlsx` y vuelve a correr — el Paso 1 lo regenera (perdiendo progreso del Paso 2).

### "El archivo está abierto en Excel"

Detectado por la presencia de `~$EMIS_Con_Historia_Fiscal.xlsx`. Cierra el Excel y vuelve a correr.

### "No hay EMIS pendientes"

Estado normal después de procesar todos los `Facturado=False`. En modo Diario el script sale rápido. Si quieres revalidar, corre con Semanal.

### El Paso 2 procesa demasiados DUNS aunque sea Diario

Significa que muchos `Facturado=False` están con `Revisado_CRM=False`. Suele ser: corridas anteriores interrumpidas que no terminaron de marcarlos. Deja correr hasta el final (atomic + flush every 5 protege).

### Fuente_Match queda como `sin_match` para una empresa que sí debería matchear

Diagnóstico con `Audit_CRM_Match.py --term <nombre>` para ver si:
- La empresa existe en `Extraer_EmpresasU4O` (con cualquier Name).
- Está mapeada en `EmpresasHomologadas`.
- Sus tokens significativos coinciden con los del nombre EMIS (descartando stopwords).

Si nada de eso aplica, el match no es alcanzable con la lógica actual; típicamente requiere agregar una variante en `EmpresasHomologadas`.
