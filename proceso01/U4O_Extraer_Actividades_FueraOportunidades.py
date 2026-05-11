"""
================================================================================
U4O_Extraer_Actividades_FueraOportunidades.py
================================================================================

PROPÓSITO
---------
Extrae actividades (Task/Event) y métricas Einstein (EAC) para contactos
NO REGISTRADOS en oportunidades U4O, dentro del umbral de seguimiento de
180 días, usando el silo de asesores U4O.

Es el SEGUNDO paso del pipeline de actividades. Se ejecuta DESPUÉS de
DentroOportunidades. NO limpia las tablas destino — sólo agrega registros
nuevos sobre lo ya extraído.

DEFINICIÓN: "Cuenta caliente"
------------------------------
Una cuenta (empresa) se considera CALIENTE cuando ocurre al menos una de
estas señales del equipo U4O:
  (a) Un asesor del silo creó una oportunidad U4O para esa cuenta en los
      últimos 24 meses (ventana extendida para capturar relación post-venta:
      seguimiento del asesor a contactos meses después del cierre).
  (b) Un asesor del silo registró Task o Event con algún contacto de esa
      cuenta (con AccountId no nulo) en los últimos 180 días.

UNIVERSO DE CONTACTOS A PROCESAR
---------------------------------
Un contacto entra al proceso si cumple TODAS estas condiciones:
  1. No fue capturado ya por DentroOportunidades (no está en
     Extraer_ActividadesU4O ni en Extraer_EinsteinCRM).
  2. No tiene oportunidad U4O en el último año.
  3. Cumple AL MENOS UNA:
       - Tiene Task o Event directo con un asesor del silo en 180 días, o
       - Su cuenta es CALIENTE (definición arriba).

ALCANCE POR CANAL
-----------------
| Tipo de actividad   | Owner del contacto         | ¿Entra? |
|---------------------|----------------------------|---------|
| Task con asesor     | Asesor                     | ✅      |
| Task con asesor     | Cualquier otro             | ✅      |
| Event con asesor    | Asesor                     | ✅      |
| Event con asesor    | Cualquier otro             | ✅      |
| ActivityMetric EAC  | Asesor + cuenta caliente   | ✅      |
| ActivityMetric EAC  | Asesor + cuenta NO caliente| ❌      |
| ActivityMetric EAC  | Otro   + cuenta caliente   | ✅      |
| ActivityMetric EAC  | Otro   + cuenta NO caliente| ❌      |

NOTA: el filtro de Task/Event en Salesforce siempre exige `OwnerId IN asesores`
(Owner de la actividad), independientemente de quién sea Owner del contacto.

CASO DE USO TÍPICO
------------------
Contacto atendido sólo por correos EAC (Einstein Activity Capture) sin Task
ni Event registrado, sin oportunidad VEC, pero cuya empresa está siendo
trabajada por el equipo. Ejemplo: un contacto recibe un email del asesor que
queda registrado en ActivityMetric pero no en Task; otro contacto de la
misma empresa sí tiene una oportunidad nueva → la cuenta es caliente y el
primer contacto entra a la extracción de EAC.

TABLAS DESTINO
--------------
- Extraer_ActividadesU4O   (Task + Event)
- Extraer_EinsteinCRM      (ActivityMetric)
================================================================================
"""

import unicodedata
from datetime import datetime
from simple_salesforce.exceptions import SalesforceMalformedRequest
import Conexiones


def normalizeDate(datestring):
    """
    Normaliza formatos de fecha de Salesforce (timestamp de 13 dígitos o ISO).
    """
    if datestring is not None:
        try:
            if len(str(datestring)) == 13:
                datestring = str(datestring)
                datestring = datestring[:-3]
                datestring = datetime.fromtimestamp(int(datestring))
                datestring = str(datestring)
            else:
                datestring = datetime.strptime(str(datestring)[:-9], '%Y-%m-%dT%H:%M:%S')
                datestring = str(datestring)
        except Exception:
            pass
    return datestring


def recuperar_actividades_silo_u4o(sf, cursor):
    """
    Extrae actividades, eventos y métricas de Einstein para contactos con atención (No registrados en oportunidades)
    dentro del umbral de seguimiento de 180 días, utilizando el silo de asesores U4O.
    """
    
    # 1. Obtener la lista de asesores autorizados (El Silo)
    print("Obteniendo lista de asesores autorizados...")
    sql_query_asesores = """
        SELECT Id FROM Extraer_AsesoresU4O
        WHERE Id IN (
            SELECT OwnerId FROM Extraer_OportunidadesU4O
            WHERE CreatedDate BETWEEN DATEADD(mm,-12,GETDATE()) AND GETDATE()
        )
    """
    cursor.execute(sql_query_asesores)
    id_list_asesores = [str(row[0]) for row in cursor.fetchall()]
    
    if not id_list_asesores:
        print("No se encontraron asesores en el umbral de seguimiento.")
        return

    formatted_asesores = "','".join(id_list_asesores)

    # 2. Pre-query Salesforce: identificar CUENTAS CALIENTES y CONTACTOS CON ACTIVIDAD DIRECTA
    # ----------------------------------------------------------------------------------------
    # CUENTA CALIENTE: empresa con (a) nueva oportunidad por asesor en 180d, o
    #                              (b) Task/Event por asesor (con AccountId no nulo) en 180d.
    # CONTACTO DIRECTO: WhoId que aparece en Task/Event creado por asesor del silo en 180d.
    print("Pre-query SF: identificando cuentas calientes y contactos con actividad directa...")
    universe_accounts = set()
    universe_contacts_direct = set()

    # 2.a) Oportunidades creadas por asesores en últimos 24 meses -> aporta AccountId a cuentas calientes
    # Ventana ampliada (24m) para capturar relación post-venta: opp ganada que sigue generando
    # seguimiento del asesor con sus contactos meses después del cierre.
    query_opps = f"""
        SELECT AccountId FROM Opportunity
        WHERE OwnerId IN ('{formatted_asesores}')
        AND CreatedDate = LAST_N_DAYS:730
        AND AccountId != null
        AND IsDeleted = False
    """
    try:
        results_opps = sf.bulk.Opportunity.query(query_opps)
        for r in results_opps:
            if r.get('AccountId'):
                universe_accounts.add(r['AccountId'])
    except Exception as e:
        print(f"  Error pre-query Opportunity: {str(e)}")

    # 2.b) Task / Event creados por asesores -> aporta AccountId (cuenta caliente) + WhoId (contacto directo)
    for objeto in ['Task', 'Event']:
        query_pre = f"""
            SELECT WhoId, AccountId FROM {objeto}
            WHERE OwnerId IN ('{formatted_asesores}')
            AND CreatedDate = LAST_N_DAYS:180
            AND IsDeleted = False
        """
        try:
            results_pre = getattr(sf.bulk, objeto).query(query_pre)
            for r in results_pre:
                if r.get('AccountId'):
                    universe_accounts.add(r['AccountId'])
                if r.get('WhoId'):
                    universe_contacts_direct.add(r['WhoId'])
        except Exception as e:
            print(f"  Error pre-query {objeto}: {str(e)}")

    print(f"  Cuentas calientes detectadas    : {len(universe_accounts):,}")
    print(f"  Contactos con actividad directa : {len(universe_contacts_direct):,}")

    # 3. Cargar universos en tablas temporales (cruce eficiente y sin límite de IN)
    cursor.execute("IF OBJECT_ID('tempdb..#UniverseAccounts') IS NOT NULL DROP TABLE #UniverseAccounts")
    cursor.execute("IF OBJECT_ID('tempdb..#UniverseContactsDirect') IS NOT NULL DROP TABLE #UniverseContactsDirect")
    cursor.execute("CREATE TABLE #UniverseAccounts (Id NVARCHAR(18) PRIMARY KEY)")
    cursor.execute("CREATE TABLE #UniverseContactsDirect (Id NVARCHAR(18) PRIMARY KEY)")
    if universe_accounts:
        cursor.executemany("INSERT INTO #UniverseAccounts (Id) VALUES (?)",
                           [(a,) for a in universe_accounts])
    if universe_contacts_direct:
        cursor.executemany("INSERT INTO #UniverseContactsDirect (Id) VALUES (?)",
                           [(c,) for c in universe_contacts_direct])
    cursor.commit()

    # 4. Identificar contactos huérfanos elegibles
    # Condiciones:
    #   - No fue capturado por DentroOportunidades (no en ActividadesU4O ni en EinsteinCRM)
    #   - No tiene oportunidad U4O en el último año
    #   - Tiene actividad directa con asesor (Task/Event), o su cuenta es caliente
    print("Identificando contactos huérfanos elegibles...")
    sql_query_huerfanos = """
        SELECT [Id] FROM [ETL].[dbo].[Extraer_ContactosU4O] AS C
        WHERE NOT EXISTS (SELECT 1 FROM [ETL].[dbo].[Extraer_ActividadesU4O] WHERE WhoId = C.Id)
        AND NOT EXISTS (SELECT 1 FROM [ETL].[dbo].[Extraer_EinsteinCRM] WHERE BaseId = C.Id)
        AND NOT EXISTS (
            SELECT 1 FROM [ETL].[dbo].[Extraer_OportunidadesU4O] O
            WHERE O.VEC_BusinessContact__c = C.Id
            AND O.CreatedDate BETWEEN DATEADD(yy,-1, GETDATE()) AND GETDATE()
        )
        AND (
            C.Id IN (SELECT Id FROM #UniverseContactsDirect)
            OR C.AccountId IN (SELECT Id FROM #UniverseAccounts)
        )
    """
    cursor.execute(sql_query_huerfanos)
    id_list_huerfanos = [str(row[0]) for row in cursor.fetchall()]

    cursor.execute("DROP TABLE #UniverseAccounts")
    cursor.execute("DROP TABLE #UniverseContactsDirect")
    cursor.commit()

    if not id_list_huerfanos:
        print("No hay contactos huérfanos elegibles para procesar.")
        return

    # Configuración de lotes
    batch_size = 1000
    print(f"Procesando {len(id_list_huerfanos)} contactos en lotes de {batch_size}...")
    
    # Campos para extracción
    actividad_fields = ['Id', 'AccountId', 'ActivityDate', 'CreatedById', 'CreatedDate', 'Description', 'Subject',
                        'OwnerId', 'RecordTypeId', 'WhoId']
    einstein_fields = ['Id', 'BaseId', 'BaseType', 'LastActivityDateTime', 'NextActivityDateTime']
    
    for i in range(0, len(id_list_huerfanos), batch_size):
        batch_contactos = id_list_huerfanos[i:i + batch_size]
        formatted_contactos = "','".join(batch_contactos)
        
        # --- PARTE A: TASK Y EVENT (Silo de Asesores) ---
        for objeto in ['Task', 'Event']:
            query = f"""
                SELECT {','.join(actividad_fields)}
                FROM {objeto}
                WHERE WhoId IN ('{formatted_contactos}')
                AND OwnerId IN ('{formatted_asesores}')
                AND IsDeleted=False
                ORDER BY CreatedDate DESC
            """
            try:
                results = getattr(sf.bulk, objeto).query(query)
                
                if results:
                    print(f"Lote {i // batch_size + 1}: Encontradas {len(results)} {objeto}s para este bloque.")
                    task_list_insert = []
                    for record in results:
                        record['CreatedDate'] = normalizeDate(record.get('CreatedDate'))
                        row = [record.get(field) for field in actividad_fields]
                        task_list_insert.append(row)
                    
                    cursor.executemany("INSERT INTO Extraer_ActividadesU4O ({}) VALUES ({})".format(
                        ','.join(actividad_fields), ','.join(['?' for _ in actividad_fields])), task_list_insert)
                    cursor.commit()
            except Exception as e:
                print(f"Error consultando {objeto} en lote {i // batch_size + 1}: {str(e)}")
        
        # --- PARTE B: EINSTEIN ACTIVITY METRIC ---
        query_einstein = f"""
            SELECT {','.join(einstein_fields)}
            FROM ActivityMetric
            WHERE BaseId IN ('{formatted_contactos}')
            AND LastActivityDateTime = LAST_N_DAYS:180
            AND IsDeleted=False
        """
        try:
            results_e = sf.bulk.ActivityMetric.query(query_einstein)
            
            if results_e:
                print(f"Lote {i // batch_size + 1}: Encontradas {len(results_e)} métricas de Einstein.")
                einstein_list_insert = []
                for record in results_e:
                    record['LastActivityDateTime'] = normalizeDate(record.get('LastActivityDateTime'))
                    record['NextActivityDateTime'] = normalizeDate(record.get('NextActivityDateTime'))
                    row = [record.get(field) for field in einstein_fields]
                    einstein_list_insert.append(row)
                
                cursor.executemany("INSERT INTO Extraer_EinsteinCRM ({}) VALUES ({})".format(
                    ','.join(einstein_fields), ','.join(['?' for _ in einstein_fields])), einstein_list_insert)
                cursor.commit()
        except Exception as e:
            print(f"Error consultando Einstein en lote {i // batch_size + 1}: {str(e)}")


def main(origen):
    startTime = datetime.now()
    print(f"Iniciando proceso: U4O_Extraer_Actividades  : {startTime}")
    
    try:
        sf = Conexiones.connect_SF(origen)
        conn_sql_server, cursor = Conexiones.connect_ETL_local_sql(origen)
        cursor.fast_executemany = True
        
        recuperar_actividades_silo_u4o(sf, cursor)
    
    except Exception as e:
        print(f"Error crítico en la ejecución: {str(e)}")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()
        if 'conn_sql_server' in locals() and conn_sql_server:
            conn_sql_server.close()
        print('Recuperación Finalizada | Tiempo de ejecución:', datetime.now() - startTime)


if __name__ == "__main__":
    main(None)