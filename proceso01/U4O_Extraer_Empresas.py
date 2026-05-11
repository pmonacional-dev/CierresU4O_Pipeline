import unicodedata
from datetime import datetime
from simple_salesforce.exceptions import SalesforceMalformedRequest
import Conexiones


def normalizeText(text):
    if text is not None:
        try:
            text = unicodedata.normalize('NFD', text)
            text = text.strip()
            text = text.encode('ascii', 'ignore')
            text = text.decode("utf-8")
        except (TypeError, NameError):
            pass
    return str(text)


def normalizeDate(datestring):
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


def main(origen):
    #origen = "Erik" # Descomentar si se requiere forzar el origen
    startTime = datetime.now()
    print(f"Iniciando extracción de empresas: {startTime}")
    
    sf = Conexiones.connect_SF(origen)
    conn_sql_server, cursor = Conexiones.connect_ETL_local_sql(origen)
    
    # Optimizaciones de sesión y cursor
    sf.session.headers.update({'Sforce-Transport-Settings': 'chunkSize=200'})
    cursor.fast_executemany = True
    
    fields = [
        'Id', 'ADV_Tax_ID__c', 'VEC_ID_Empresa__c', 'ParentId', 'OwnerId', 'Name',
        'ADV_Razon_Social__c', 'NumberOfEmployees', 'VEC_Ranking__c', 'Website',
        'BillingCity', 'BillingCountry', 'BillingPostalCode', 'BillingState', 'BillingStreet',
        'CreatedDate', 'Industry', 'VEC_Transformation__c', 'VEC_Commerce__c', 'VEC_Services__c',
        'VEC_Government__c', 'AnnualRevenue', 'RecordTypeId'
        ]
    
    print("1. Limpiando historial de empresas en SQL Server...")
    try:
        cursor.execute("DELETE FROM Extraer_EmpresasU4O")
        cursor.commit()
    except Exception as e:
        print(f"Error al limpiar tabla: {str(e)}")
    
    # Queries base para tipos específicos
    queries_iniciales = [
        {
            "nombre": "Empresas en Oportunidades",
            "soql": f"""SELECT {','.join(fields)} FROM Account WHERE IsDeleted=False AND Id IN (
                        SELECT AccountId FROM Opportunity WHERE IsDeleted=False
                        AND StageName IN ('Cerrada Ganada','Cerrada Perdida', 'Oportunidad', 'Propuesta', 'Negociación')
                        AND RecordTypeId IN ('01241000001EgMRAA0','01241000001EgMSAA0','01241000001EgMTAA0'))"""
            },
        {
            "nombre": "Empresas U4O sin Oportunidades",
            "soql": f"""SELECT {','.join(fields)} FROM Account WHERE IsDeleted=False
                        AND RecordTypeId = '01241000000yvXDAAY' AND Industry != null AND Id NOT IN (
                        SELECT AccountId FROM Opportunity WHERE IsDeleted=False
                        AND StageName IN ('Cerrada Ganada','Cerrada Perdida', 'Oportunidad', 'Propuesta', 'Negociación')
                        AND RecordTypeId IN ('01241000001EgMRAA0','01241000001EgMSAA0','01241000001EgMTAA0'))"""
            }
        ]
    
    for q in queries_iniciales:
        print(f"Ejecutando: {q['nombre']}...")
        try:
            results = sf.bulk.Account.query(q['soql'])
            if results:
                task_list = []
                for record in results:
                    record['CreatedDate'] = normalizeDate(record.get('CreatedDate'))
                    task_list.append([record.get(f) for f in fields])
                
                cursor.executemany("INSERT INTO Extraer_EmpresasU4O ({}) VALUES ({})".format(
                    ','.join(fields), ','.join(['?' for _ in fields])), task_list)
                cursor.commit()
                print(f"   - Registros insertados: {len(task_list)}")
        except Exception as e:
            print(f"Error en {q['nombre']}: {str(e)}")
    
    print("2. Enriquecimiento: Empresas registradas en actividades pero no en catálogo U4O...")
    try:
        # EFICIENCIA: Obtenemos todos los IDs faltantes de una vez
        sql_missing_ids = """
             SELECT DISTINCT AccountId FROM Extraer_ActividadesU4O
             WHERE AccountId IS NOT NULL
             AND AccountId IN (SELECT Id FROM Extraer_EmpresasU4O WHERE [RecordTypeId] = '01241000000yvXDAAY')
        """
        cursor.execute(sql_missing_ids)
        all_missing_ids = [str(row[0]) for row in cursor.fetchall()]
        #print(all_missing_ids)
        if all_missing_ids:
            # Procesamos en lotes de 2000 (Bulk Select eficiente)
            batch_size = 2000
            print(f"   - Total de IDs faltantes encontrados: {len(all_missing_ids)}")
            
            for i in range(0, len(all_missing_ids), batch_size):
                chunk = all_missing_ids[i:i + batch_size]
                formatted_ids = "','".join(chunk)
                
                soql_bulk = f"SELECT {','.join(fields)} FROM Account WHERE Id IN ('{formatted_ids}') AND RecordTypeId IN ('01241000000yvXDAAY')"
                
                # Usamos Bulk API únicamente
                result_chunk = sf.bulk.Account.query(soql_bulk)
                
                if result_chunk:
                    chunk_list = []
                    for record in result_chunk:
                        record['CreatedDate'] = normalizeDate(record.get('CreatedDate'))
                        chunk_list.append([record.get(f) for f in fields])
                    
                    cursor.executemany("INSERT INTO Extraer_EmpresasU4O ({}) VALUES ({})".format(
                        ','.join(fields), ','.join(['?' for _ in fields])), chunk_list)
                    cursor.commit()
                    print(f"   - Lote {i // batch_size + 1} procesado ({len(chunk_list)} registros)")
        else:
            print("   - No se encontraron empresas adicionales en actividades.")
    
    except Exception as e:
        print(f"Error en fase de enriquecimiento: {str(e)}")
    
    finally:
        if cursor: cursor.close()
        if conn_sql_server: conn_sql_server.close()
        print(f"Extraer_EmpresasU4O | Tiempo total: {datetime.now() - startTime}")


if __name__ == "__main__":
    main(None)