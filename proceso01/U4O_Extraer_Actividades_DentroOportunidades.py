"""
================================================================================
U4O_Extraer_Actividades_DentroOportunidades.py
================================================================================

PROPÓSITO
---------
Extrae actividades (Task/Event), historial de oportunidades y métricas Einstein
(EAC) para contactos REGISTRADOS en oportunidades U4O, dentro del umbral de
seguimiento de 180 días, usando el silo de asesores U4O.

Es el PRIMER paso del pipeline de actividades: LIMPIA y repuebla las tablas
destino. Después debe correr FueraOportunidades para cubrir contactos sin
oportunidad pero con atención del equipo.

DEFINICIÓN: "Contacto atendido" (universo Einstein de este script)
-------------------------------------------------------------------
Un contacto se considera atendido para extraer su ActivityMetric si cumple
al menos una de:
  (a) Aparece como VEC_BusinessContact__c en alguna oportunidad U4O creada
      en el último año, o
  (b) Aparece como WhoId en alguna Task/Event ya extraída en esta corrida y
      no es él mismo un asesor.

ALCANCE POR CANAL
-----------------
| Tipo de actividad         | Condición sobre el contacto / actividad     | ¿Entra? |
|---------------------------|---------------------------------------------|---------|
| Task con asesor (180d)    | Con AccountId != null                       | ✅      |
| Task con asesor (180d)    | Con AccountId NULL                          | ❌      |
| Event con asesor (180d)   | Con AccountId != null                       | ✅      |
| Event con asesor (180d)   | Con AccountId NULL                          | ❌      |
| OpportunityHistory (180d) | Creado por asesor del silo                  | ✅      |
| ActivityMetric / EAC      | Contacto atendido (def. arriba)             | ✅      |
| ActivityMetric / EAC      | Contacto NO atendido                        | ❌      |

NOTA: el filtro `OwnerId IN asesores` se aplica al Owner de la actividad
(Task.OwnerId, Event.OwnerId), NO al Owner del contacto. El contacto puede
pertenecer a cualquier persona; lo que importa es que la actividad fue
creada por un asesor del silo.

LO QUE QUEDA PARA FueraOportunidades.py
----------------------------------------
- Task/Event con AccountId = NULL (cold outreach).
- Contactos sin oportunidad U4O en último año atendidos sólo por EAC.
- Contactos sin oportunidad cuya cuenta es "caliente" (ver doc de FueraOportunidades).

TABLAS DESTINO
--------------
- Extraer_ActividadesU4O           (Task + Event)
- Extraer_HistoriaOportunidadesU4O (OpportunityHistory)
- Extraer_EinsteinCRM              (ActivityMetric)
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


def extraer_actividades_atendidos_u4o(sf, cursor):
    """
    Extrae actividades, eventos y métricas de Einstein para contactos con atención (Registrados en oportunidades)
    dentro del umbral de seguimiento de 180 días, utilizando el silo de asesores U4O.
    """
    
    # 1. Limpieza inicial de tablas (Estructura de seguimiento actual)
    print("Limpiando tablas de actividades, historial y Einstein...")
    try:
        cursor.execute("DELETE FROM Extraer_ActividadesU4O")
        cursor.execute("DELETE FROM Extraer_HistoriaOportunidadesU4O")
        cursor.execute("DELETE FROM Extraer_EinsteinCRM")
        cursor.commit()
    except Exception as e:
        print(f"Error limpiando tablas: {str(e)}")
    
    # 2. Obtener la lista de asesores autorizados (El Silo)
    print("Obteniendo lista de asesores autorizados (activos en Oportunidades)...")
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
    
    # 3. Extraer Task y Event (Silo de Asesores - Últimos 180 días)
    # Usamos lotes de asesores por si la lista es muy larga para el SOQL
    batch_size_asesores = 200
    actividad_fields = ['Id', 'AccountId', 'ActivityDate', 'CreatedById', 'CreatedDate', 'Description', 'Subject',
                        'OwnerId', 'RecordTypeId', 'WhoId']
    
    print(f"Extrayendo Task y Event para {len(id_list_asesores)} asesores (180 días)...")
    for i in range(0, len(id_list_asesores), batch_size_asesores):
        batch_asesores = id_list_asesores[i:i + batch_size_asesores]
        formatted_asesores = "','".join(batch_asesores)
        
        for objeto in ['Task', 'Event']:
            query = f"""
                SELECT {','.join(actividad_fields)}
                FROM {objeto}
                WHERE OwnerId IN ('{formatted_asesores}')
                AND CreatedDate = LAST_N_DAYS:180
                AND AccountId != null AND IsDeleted=False
            """
            try:
                results = getattr(sf.bulk, objeto).query(query)
                if results:
                    insert_list = []
                    for record in results:
                        record['CreatedDate'] = normalizeDate(record.get('CreatedDate'))
                        row = [record.get(field) for field in actividad_fields]
                        insert_list.append(row)

                    cursor.executemany("INSERT INTO Extraer_ActividadesU4O ({}) VALUES ({})".format(
                        ','.join(actividad_fields), ','.join(['?' for _ in actividad_fields])), insert_list)
                    cursor.commit()
            except Exception as e:
                print(f"Error consultando {objeto}: {str(e)}")

        # Task adicional por RecordType (sin filtro de AccountId) — captura tareas de tipo '01241000000yvXWAAY' / Actividades_Escuela_Vinculacion
        # Por alguna razón se asociaron a Tuvis este tipo de tareas, cuando se tuvo que crear un tipo específico para esta línea.
        # Al no existir relación de registros Tuvis con una AccountId, debera existir una conversión correcta de un prospecto a contacto y generación de oportunidad para metricas de conversión
        # desde esta canal hacia embudo
        
        query_task_rt = f"""
            SELECT {','.join(actividad_fields)}
            FROM Task
            WHERE OwnerId IN ('{formatted_asesores}')
            AND CreatedDate = LAST_N_DAYS:180
            AND IsDeleted=False
            AND RecordTypeId = '01241000000yvXWAAY'
        """
        try:
            results_rt = sf.bulk.Task.query(query_task_rt)
            if results_rt:
                insert_list_rt = []
                for record in results_rt:
                    record['CreatedDate'] = normalizeDate(record.get('CreatedDate'))
                    row = [record.get(field) for field in actividad_fields]
                    insert_list_rt.append(row)

                cursor.executemany("INSERT INTO Extraer_ActividadesU4O ({}) VALUES ({})".format(
                    ','.join(actividad_fields), ','.join(['?' for _ in actividad_fields])), insert_list_rt)
                cursor.commit()
        except Exception as e:
            print(f"Error consultando Task RecordType 01241000000yvXWAAY: {str(e)}")
    
    # 4. Extraer Historial de Oportunidades (180 días)
    print("Extrayendo Historial de Oportunidades (180 días)...")
    history_fields = ['OpportunityId', 'CreatedById', 'CloseDate', 'CurrencyIsoCode', 'Amount', 'StageName',
                      'CreatedDate']
    formatted_all_asesores = "','".join(id_list_asesores)
    query_history = f"""
        SELECT {','.join(history_fields)} FROM OpportunityHistory
        WHERE CreatedById IN ('{formatted_all_asesores}') AND CreatedDate = LAST_N_DAYS:180
        AND IsDeleted=False
    """
    try:
        res_hist = sf.bulk.OpportunityHistory.query(query_history)
        if res_hist:
            hist_insert = []
            for r in res_hist:
                r['CreatedDate'] = normalizeDate(r.get('CreatedDate'))
                hist_insert.append([r.get(f) for f in history_fields])
            cursor.executemany("INSERT INTO Extraer_HistoriaOportunidadesU4O ({}) VALUES ({})".format(
                ','.join(history_fields), ','.join(['?' for _ in history_fields])), hist_insert)
            cursor.commit()
    except Exception as e:
        print(f"Error en OpportunityHistory: {str(e)}")
    
    # 5. Identificar contactos atendidos (Para Einstein)
    print("Identificando contactos atendidos (Ops 1 año + Actividades 180 días)...")
    sql_query_atendidos = """
        SELECT DISTINCT Id FROM Extraer_ContactosU4O WHERE Id IN (
            SELECT DISTINCT VEC_BusinessContact__c FROM Extraer_OportunidadesU4O
            WHERE CreatedDate BETWEEN DATEADD(yy,-1, GETDATE()) AND GETDATE()
            AND VEC_BusinessContact__c IS NOT NULL
        )
        OR Id IN (
            SELECT DISTINCT WhoId FROM Extraer_ActividadesU4O
            WHERE WhoId NOT IN (SELECT Id FROM Extraer_AsesoresU4O)
        )
    """
    cursor.execute(sql_query_atendidos)
    id_list_atendidos = [str(row[0]) for row in cursor.fetchall()]
    
    # 6. Extraer Einstein Activity Metric (180 días - Por Lotes de Contactos)
    if id_list_atendidos:
        batch_size_contacts = 1000
        einstein_fields = ['Id', 'BaseId', 'BaseType', 'LastActivityDateTime', 'NextActivityDateTime']
        print(f"Extrayendo Einstein para {len(id_list_atendidos)} contactos...")
        
        for i in range(0, len(id_list_atendidos), batch_size_contacts):
            batch_contacts = id_list_atendidos[i:i + batch_size_contacts]
            formatted_contacts = "','".join(batch_contacts)
            
            query_e = f"""
                SELECT {','.join(einstein_fields)} FROM ActivityMetric
                WHERE BaseId IN ('{formatted_contacts}') AND LastActivityDateTime = LAST_N_DAYS:180
                AND IsDeleted=False
            """
            try:
                res_e = sf.bulk.ActivityMetric.query(query_e)
                if res_e:
                    e_insert = []
                    for r in res_e:
                        r['LastActivityDateTime'] = normalizeDate(r.get('LastActivityDateTime'))
                        r['NextActivityDateTime'] = normalizeDate(r.get('NextActivityDateTime'))
                        e_insert.append([r.get(f) for f in einstein_fields])
                    cursor.executemany("INSERT INTO Extraer_EinsteinCRM ({}) VALUES ({})".format(
                        ','.join(einstein_fields), ','.join(['?' for _ in einstein_fields])), e_insert)
                    cursor.commit()
            except Exception as e:
                print(f"Error en Einstein batch {i}: {str(e)}")
    
    # 7. Limpieza final de miembros fuera del equipo (Hardcoded IDs)
    print("Ejecutando limpieza final de Owners excluidos...")
    cursor.execute("""
        DELETE FROM Extraer_ActividadesU4O
        WHERE OwnerId IN ('0053f000000Fe2SAAS','00541000002payfAAA','0053f000000mO5wAAE','0052M000008gKZwQAM','00541000007MjgWAAS')
    """)
    cursor.commit()


def main(origen):
    startTime = datetime.now()
    print(f"Iniciando proceso: U4O_Extraer_Actividades : {startTime}")
    
    try:
        sf = Conexiones.connect_SF(origen)
        conn_sql_server, cursor = Conexiones.connect_ETL_local_sql(origen)
        cursor.fast_executemany = True
        
        extraer_actividades_atendidos_u4o(sf, cursor)
    
    except Exception as e:
        print(f"Error crítico: {str(e)}")
    finally:
        if 'cursor' in locals() and cursor: cursor.close()
        if 'conn_sql_server' in locals() and conn_sql_server: conn_sql_server.close()
        print('Proceso finalizado: U4O_Extraer_Actividades | Tiempo total:', datetime.now() - startTime)


if __name__ == "__main__":
    main(None)