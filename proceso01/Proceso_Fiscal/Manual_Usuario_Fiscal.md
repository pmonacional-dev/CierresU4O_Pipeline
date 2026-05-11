# Manual de Usuario: Sistema de Limpieza Fiscal y Busqueda Estructurada

## 1. Introduccion

Este sistema resuelve el problema de **homologacion de nombres de empresas** provenientes de Salesforce y su **perfilamiento fiscal** a partir de datos de facturacion (CFDI). El flujo completo transforma datos dispersos en un reporte consolidado con trazabilidad, y ofrece un buscador interactivo para consultar ecosistemas empresariales.

### Flujo general

```
AF_Facturas.xlsx                 SQL Server (ETL)
  (datos fiscales)              (empresas Salesforce + tabla de homologacion)
        |                               |
        +----------- JOIN --------------+
                       |
              [1] U4O_Limpieza_Fiscal.py
              (Tier 1: Homologacion local)
              (Tier 2: Lookup SINDATA)
              (Registro CRM: empresas nuevas)
                       |
                       v
        Reporte_Fiscal_Historico.csv  <-- PRODUCTO INTERMEDIO
              (reporte consolidado + JSON de evidencia)
                       |
                       v
              [2] U4O_Busqueda_Estructurada.py
              (buscador interactivo 360°)
```

> [!IMPORTANT]
> **Dependencia Crítica**: El buscador `U4O_Busqueda_Estructurada.py` **depende directamente** de la existencia del archivo `Reporte_Fiscal_Historico.csv`. Por lo tanto, siempre se debe ejecutar primero el script de limpieza si hay datos nuevos.

### Componentes (Carpeta: `Proceso_Fiscal/`)

| Componente | Archivo | Rol |
|---|---|---|
| Entrada fiscal | `AF_Facturas.xlsx` | Facturas CFDI con RFC, razon social, CP, regimen |
| Motor de limpieza | `U4O_Limpieza_Fiscal.py` | Homologacion en 2 tiers + registro CRM |
| Reporte de salida | `Reporte_Fiscal_Historico.csv` | Resultado consolidado con trazabilidad |
| Buscador | `U4O_Busqueda_Estructurada.py` | Consulta interactiva por nombre o RFC |
| Conexiones | `../Conexiones.py` | Modulo centralizado (ubicado en la raiz del proyecto) |

---

## 2. Prerrequisitos

### Software
- Python 3.10 o superior
- Dependencias listadas en `requirements.txt`:
  - `pandas` - manipulacion de datos
  - `pyodbc` - conexion a SQL Server
  - `openpyxl` - lectura de archivos Excel (dependencia de pandas)

### Bases de datos
El sistema utiliza dos conexiones configuradas en `Conexiones.py`:

| Conexion | Funcion | Servidor | Base de datos |
|---|---|---|---|
| ETL local | `connect_ETL_local_sql(origen)` | `EDATA` (Erik) / `L03523797L03` (Antonio) | `ETL` |
| SINDATA SaaS | `connect_SINDATA_saas_sql()` | `www.edatasoluciones.com,8081` | `SIN_Data` |

### Archivo de entrada
- `AF_Facturas.xlsx` debe estar en la carpeta `Proceso_Fiscal/`
- **El archivo debe estar cerrado** antes de ejecutar el proceso

---

## 3. Archivo de entrada: AF_Facturas.xlsx

Este archivo contiene los datos fiscales extraidos de facturas CFDI. Las columnas requeridas son:

| Columna | Descripcion | Ejemplo |
|---|---|---|
| `ID Cliente` | Identificador unico del cliente (llave de cruce con Salesforce) | `001A000001XyZ` |
| `RFC receptor` | Registro Federal de Contribuyentes del receptor | `ABC123456XY9` |
| `Nombre del Receptor` | Razon social tal como aparece en la factura | `EMPRESA EJEMPLO SA DE CV` |
| Codigo Postal* | Codigo postal del domicilio fiscal | `06600` |
| Regimen Fiscal* | Regimen fiscal del receptor | `601 - General de Ley` |
| Fecha de emision* | Fecha en que se emitio la factura | `2025-06-15` |

> *Estas columnas se detectan dinamicamente por coincidencia parcial del nombre. El sistema busca patrones como `digoPostal`, `gimenFiscal` y `Fecha de emisi` en los encabezados. Esto permite flexibilidad si los nombres de columna varian ligeramente entre versiones del archivo.

---

## 4. Proceso de Limpieza Fiscal: U4O_Limpieza_Fiscal.py

### Ejecucion

```python
python U4O_Limpieza_Fiscal.py
```

La funcion principal es:

```python
process_cruce_datos(origen="Erik", test_insert=True)
```

| Parametro | Tipo | Descripcion |
|---|---|---|
| `origen` | `str` | Contexto de usuario: `"Erik"` o `"Antonio"`. Determina el servidor SQL local. |
| `test_insert` | `bool` | Si es `True`, inserta empresas no homologadas en el CRM. Si es `False`, solo genera el reporte sin modificar el CRM. |

### Paso a paso del proceso

#### Paso 1: Extraccion ETL

Consulta dos tablas del servidor SQL local:

- **`Extraer_EmpresasU4O`**: Empresas de Salesforce con su ID, nombre y `VEC_ID_Empresa__c` (llave de cruce).
- **`EmpresasHomologadas`**: Tabla de mapeo que relaciona nombres originales (`NombreOriginal`) con su nombre canonico (`NombrePrincipal`).

#### Paso 2: Homologacion Tier 1 (base de datos local)

Construye un motor de busqueda en memoria a partir de la tabla `EmpresasHomologadas`:

- **Diccionario de homologacion**: Mapea cada `NombreOriginal` (en mayusculas) a su `NombrePrincipal`.
- **Diccionario de variantes**: Agrupa todas las variantes conocidas bajo cada nombre principal.
- **Conjunto de principales**: Identifica nombres que ya son canonicos.

Cada empresa de Salesforce se busca en este diccionario. Si se encuentra, se asigna el `NombreHomologado` correspondiente.

#### Paso 3: Cruce con datos fiscales (JOIN)

Realiza un **INNER JOIN** entre:
- Datos de Salesforce (campo `VEC_ID_Empresa__c`)
- Datos de facturacion Excel (campo `ID Cliente`)

Solo se conservan las empresas que existen en ambas fuentes.

#### Paso 4: Consolidacion de perfiles fiscales

Se produce **una sola fila por `RFC receptor`**. Los atributos que pueden variar a lo largo del tiempo (`Codigo Postal`, `Regimen Fiscal`, `Fecha de emision`) se serializan como objetos JSON con la siguiente forma:

```json
{
  "Ultimo": "64410",
  "Historico": ["64410", "64411", "06600"]
}
```

- `Ultimo`: el valor del registro fiscal mas reciente (lo que actualmente esta vigente).
- `Historico`: lista de todos los valores unicos observados, ordenados de mas reciente a mas antiguo.

Reglas:

- Se ordena por fecha de emision descendente antes de agrupar, para que el primer valor de cada grupo sea el mas reciente.
- Los regimenes numericos `601.0` se normalizan a `"601"` (string limpio).
- Las fechas se formatean como `YYYY/MM/DD`.
- Si varios registros de Salesforce comparten un mismo `RFC receptor`, los `Name` historicos se preservan como variantes en el campo `Validacion JSON` (busqueda bidireccional).
- Si el registro mas reciente no tenia `NombreHomologado` pero algun registro historico si, el valor homologado se preserva (no se pierde el match Tier 1).

#### Paso 5: Homologacion Tier 2 (SINDATA)

Para empresas que **no** fueron homologadas en el Tier 1:

1. Conecta al servidor SINDATA SaaS
2. Consulta la tabla `[SIN_Data].[dbo].[EmpresaCRM]`
3. Busca coincidencia exacta (case-insensitive) del nombre de la empresa
4. Si encuentra coincidencia, asigna el `NombreHomologado`

#### Paso 6: Registro CRM en lote (solo si `test_insert=True`)

Para empresas que **siguen sin homologar** despues de ambos tiers:

1. Obtiene el siguiente ID disponible en la tabla `EmpresaCRM`
2. Inserta cada empresa nueva con los siguientes datos:

| Campo | Valor |
|---|---|
| `EmpresaCRM_Id` | ID autoincremental |
| `EmpresaCRM_Nombre` | Nombre original de la empresa |
| Estatus | `'Pendiente'` |
| Origen | `'Oportunidades'` |
| Fecha | Timestamp de ejecucion |

3. Actualiza el DataFrame en memoria para que el reporte refleje la insercion
4. Registra cada insercion en el log: `Registrando en CRM: [nombre] (ID: [id])`

> **Ciclo de data enrichment**: Las empresas se insertan con estatus `'Pendiente'`. Posteriormente, un operador humano debe revisar y homologar estas empresas en el CRM, cambiando su estatus. En la siguiente ejecucion, estas empresas ya seran encontradas por el Tier 2.

#### Paso 7: Generacion de evidencia JSON y guardado

Para cada registro se genera un campo `Validacion JSON` con la siguiente estructura:

```json
{
  "EntradaReporte": "Nombre tal como llego del ETL",
  "ValidaExistencia": "Si | No | Si (Es Principal) | Si (SINDATA/Match)",
  "NombrePrincipal": "Nombre canonico asignado",
  "Variantes": ["variante1", "variante2", "Nombre del Receptor (si difiere)"]
}
```

Los valores posibles de `ValidaExistencia` son:

| Valor | Significado |
|---|---|
| `Si` | Se encontro como variante en la tabla de homologacion (Tier 1) |
| `Si (Es Principal)` | El nombre ya es un nombre principal/canonico |
| `Si (SINDATA/Match)` | Se encontro en el CRM de SINDATA (Tier 2) |
| `No` | No se encontro en ninguna fuente |

> **Enriquecimiento con Nombre del Receptor**: Si el `Nombre del Receptor` de la factura difiere del `Name` de Salesforce y del `NombrePrincipal`, se agrega automaticamente como variante adicional. Esto permite busqueda bidireccional: buscar por la razon social de la factura encuentra a la empresa de Salesforce, y viceversa. Ejemplo: `QBE DE MEXICO` tiene como variante a `ZURICH ASEGURADORA MEXICANA` porque comparten RFC aunque sus nombres difieran.

Adicional, se genera la columna `VariantesIdEmpresa`:

```json
{
  "FEMSA SERVICIOS S.A. de C.V.": "0013f000006yyOEAAY",
  "OXXO MORELOS": "0013f000006zzOEBBB"
}
```

Esto integra el `IdEmpresa` (Salesforce Account Id) de cada variante presente en `Validacion JSON.Variantes` que tenga un match en Salesforce. Las variantes que solo existan en `EmpresasHomologadas` o en el CFDI (sin contraparte en SF) simplemente no aparecen en el mapa.

El resultado final se guarda como CSV en `Reporte_Fiscal_Historico.csv`.

---

## 5. Documento de salida: Reporte_Fiscal_Historico.csv

### Columnas del reporte

| Columna | Tipo | Descripcion |
|---|---|---|
| `ID Cliente` | string | Identificador del cliente (llave de cruce con `VEC_ID_Empresa__c`) |
| `Name` | string | Nombre de la empresa en Salesforce (del registro mas reciente del RFC) |
| `NombreHomologado` | string | Nombre canonico asignado por el motor de homologacion |
| `RFC receptor` | string | RFC del receptor de la factura (clave unica del reporte) |
| `Nombre del Receptor` | string | Razon social en la factura (del registro mas reciente del RFC) |
| `CodigoPostal` | JSON `{Ultimo, Historico}` | Codigo postal fiscal vigente + lista historica de CP usados |
| `RegimenFiscal` | JSON `{Ultimo, Historico}` | Regimen fiscal vigente + lista historica |
| `FechaFacturacion` | JSON `{Ultimo, Historico}` | Fecha de facturacion mas reciente + lista historica (`YYYY/MM/DD`) |
| `Validacion JSON` | JSON | Evidencia de trazabilidad de homologacion (Variantes incluye otros `Name` que comparten RFC) |
| `VariantesIdEmpresa` | JSON `{nombre: IdEmpresa}` | Mapa de cada variante a su `IdEmpresa` (Salesforce Account Id). Reemplaza la columna `Id` del esquema anterior, integrando todos los Ids de los registros que se consolidaron en este RFC mas los matches contra el catalogo SF de variantes provenientes de `EmpresasHomologadas` o del `Nombre del Receptor`. |

> **Nota de migración**: El esquema anterior tenia una columna `Id` con el Salesforce Account Id del registro mas reciente. Esa columna fue removida; los Ids ahora se entregan en `VariantesIdEmpresa`, que ademas captura los Ids de las otras variantes consolidadas bajo el mismo RFC.

### Granularidad
**1 fila por `RFC receptor`**. Las variantes de CP, Régimen y Fecha se conservan dentro de objetos JSON; ya no aparecen como filas duplicadas.

### Estructura de los objetos JSON historico

```json
{
  "Ultimo": "601",
  "Historico": ["601", "612", "626"]
}
```

- `Ultimo`: valor del registro fiscal mas reciente.
- `Historico`: valores unicos en orden de aparicion (mas reciente primero).

### Ordenamiento
- Primario: `Name` (A-Z)

### Codificacion
- UTF-8 con BOM (`utf-8-sig`) para compatibilidad con Excel en espanol

---

## 6. Buscador Estructurado: U4O_Busqueda_Estructurada.py

### Ejecucion

```python
python U4O_Busqueda_Estructurada.py
```

Se abre un prompt interactivo en terminal. 

> [!WARNING]
> **Requisito Previo**: Requiere que el archivo `Reporte_Fiscal_Historico.csv` exista en la carpeta local. Este archivo es el **consumible principal** generado por `U4O_Limpieza_Fiscal.py`. Si el archivo no existe o está desactualizado, el buscador no mostrará información reciente.

### Uso del buscador

```
--- BUSCADOR HIBRIDO (NOMBRE / RFC) - VISION 360° ---

Introduce Nombre de Empresa o RFC (o 'salir'):
```

- Escribir un **nombre de empresa** para buscar por similitud textual
- Escribir un **RFC** (10-13 caracteres alfanumericos) para buscar por identificador fiscal
- Escribir `salir`, `exit` o `q` para terminar

### Algoritmo de busqueda

El buscador evalua cada grupo de empresa contra la consulta en tres niveles de prioridad:

| Prioridad | Tipo de match | Descripcion |
|---|---|---|
| 1 | RFC Exacto | Coincidencia exacta con un RFC del grupo (score: 100%) |
| 1b | RFC Parcial | La consulta esta contenida en un RFC (score proporcional, penalizado) |
| 2 | Nombre Homologado | Similitud textual (`SequenceMatcher`) contra el nombre canonico |
| 3 | Variantes JSON | Similitud contra `EntradaReporte` y cada variante del campo JSON |

- **Umbral minimo**: 40% de similitud para aparecer en resultados
- **Resultados**: Se muestran los 5 mejores ordenados por score

### Ejemplo de resultados

```
Sugerencias encontradas:
1. [95%] GRUPO EJEMPLO - Via: Nombre Homologado
2. [78%] EJEMPLO CORP - Via: Variante (EJEMPLO CORPORATIVO)
3. [62%] EJEMPLAR SA - Via: Nombre Original (Entrada)
```

### Reporte de ecosistema 360°

Al seleccionar un resultado por su numero, se despliega el perfil fiscal completo (1 fila por RFC):

```
[GRUPO EJEMPLO]
  RFC: GEJ850101AAA | GRUPO EJEMPLO SA DE CV | CP: 06600 | Régimen: 601, 623 | Última fact: 2025/11/20
  RFC: GEJ850101BBB | GRUPO EJEMPLO NORTE    | CP: 64000 | Régimen: 601      | Última fact: 2025/08/15
```

Este reporte muestra:
- Todos los RFCs asociados al nombre homologado
- La razon social registrada en cada factura
- **CP**: codigo postal fiscal vigente (campo `Ultimo` del JSON `CodigoPostal`)
- **Regimen**: si el RFC ha usado mas de un regimen, se muestran todos separados por coma (campo `Historico`); si solo hay uno, se muestra el `Ultimo`
- **Última fact.**: fecha de facturacion mas reciente (campo `Ultimo` del JSON `FechaFacturacion`)

> Para acceder al historial completo (todos los CP/regimenes/fechas que ha usado el RFC), parsear directamente el JSON de las columnas `CodigoPostal`, `RegimenFiscal` y `FechaFacturacion` del CSV.

---

## 7. Flujo completo resumido

```
FUENTES DE DATOS                    PROCESAMIENTO                        SALIDA Y CONSUMO
================                    =============                        ================

SQL Server (ETL)                         |
+-- Extraer_EmpresasU4O ----+            |
+-- EmpresasHomologadas ----+---> [Tier 1: Homologacion local]
                             |           |
AF_Facturas.xlsx -----------+---> [JOIN por ID Cliente]
                                         |
                                  [Consolidacion fiscal]
                                         |
SINDATA (SaaS)                           |
+-- EmpresaCRM ------------+---> [Tier 2: Lookup remoto]
                             |           |
                             +<-- [Registro de nuevas        ---> Reporte_Fiscal_Historico.csv
                                   empresas 'Pendiente']
                                         |                              |
                                  [Evidencia JSON]                      |
                                                                        v
                                                              U4O_Busqueda_Estructurada.py
                                                              (consulta interactiva 360°)
```

### Ciclo de data enrichment

1. **Primera ejecucion**: Se detectan empresas sin homologar y se registran en CRM con estatus `'Pendiente'`
2. **Revision manual**: Un operador revisa las empresas pendientes en el CRM y las homologa (asigna nombre principal)
3. **Siguiente ejecucion**: Las empresas previamente pendientes ahora son encontradas por el Tier 2, cerrando el ciclo

```
[No homologada] --insert--> [Pendiente en CRM] --revision manual--> [Homologada en CRM]
                                                                           |
                                                    Tier 2 la encuentra <--+
```

---

## 8. Consulta de datos fiscales por RFC (Investigacion SAT)

### Problema

Cuando se registra un RFC nuevo que no existe en el historico de facturacion, se requiere obtener la razon social y regimen fiscal del contribuyente. Se investigo si es posible automatizar esta consulta.

### Libreria investigada: python-satcfdi

- **Repositorio**: https://github.com/SAT-CFDI/python-satcfdi/
- **Instalacion**: `pip install satcfdi`
- **Nota**: No es una libreria oficial del SAT, pero es la mas completa en Python para interactuar con servicios del SAT.

### Metodos disponibles para consulta de RFC

| Metodo | Requiere | Devuelve | Util para |
|---|---|---|---|
| `satcfdi.models.RFC` | Nada (offline) | Validacion de formato, tipo (fisica/moral), digito verificador | Validar que un RFC capturado sea sintacticamente correcto |
| `portal.rfc_valid(rfc)` | FIEL (.cer, .key, password) | `True/False` (existe en el SAT) | Confirmar que el RFC esta registrado |
| `portal.legal_name_valid(rfc, nombre)` | FIEL + razon social | `True/False` (coinciden RFC y nombre) | Verificar que la razon social sea correcta, pero se necesita conocer el nombre previamente |
| `portal.lco_details(rfc)` | FIEL | Info del LCO (contribuyentes obligados) | Consultar estatus de contribuyente obligado |
| `csf.retrieve(rfc, id_cif)` | RFC + id_cif | **Razon social, regimen fiscal, fechas** | Obtener datos fiscales completos |

### Hallazgo clave

**El SAT no expone un endpoint publico de "RFC → Razon Social + Regimen"**, ni siquiera con autenticacion FIEL. Esto es por diseno (proteccion de datos fiscales del contribuyente).

Las empresas de facturacion (PACs como Finkok, Facturama, etc.) obtienen los datos de sus clientes a traves de:

1. El receptor proporciona su **Constancia de Situacion Fiscal** (PDF descargado del SAT)
2. Del codigo QR de la constancia se extrae el `id_cif` (identificador unico de la cedula fiscal)
3. Con `csf.retrieve(rfc, id_cif)` se obtienen los datos actualizados programaticamente

### Ejemplo de validacion offline (sin FIEL)

```python
from satcfdi.models import RFC, RFCType

r = RFC("QMS950529PU4")
r.type       # RFCType.MORAL (persona moral, 3 letras iniciales)
r.is_valid() # True (digito verificador correcto)

# Persona fisica tiene 4 letras iniciales
r2 = RFC("GARC850101AB1")
r2.type      # RFCType.FISICA
```

### Ejemplo con FIEL (si se dispone de ella)

```python
from satcfdi.models import Signer
from satcfdi.portal import SATFacturaElectronica

signer = Signer.load(
    certificate=open('fiel.cer', 'rb').read(),
    key=open('fiel.key', 'rb').read(),
    password='contraseña'
)

portal = SATFacturaElectronica(signer)
portal.login()

portal.rfc_valid("QMS950529PU4")  # True/False
```

### Conclusion para este proyecto

Para el registro de RFCs nuevos en el buscador, la estrategia viable es:

1. **Validacion offline** del formato RFC con `satcfdi.models.RFC` (sin dependencias externas)
2. **Captura manual** de razon social y regimen fiscal por parte del usuario
3. **Futuro**: si se obtiene acceso a la FIEL del emisor, se puede agregar validacion de existencia contra el SAT con `portal.rfc_valid()`
