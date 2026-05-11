import unicodedata
from datetime import datetime
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
                datestring = datetime.strptime(datestring[:-9], '%Y-%m-%dT%H:%M:%S')
                datestring = str(datestring)
        except (TypeError, NameError):
            pass
    return datestring


def main(origen):
    #origen = "Erik"
    startTime = datetime.now()
    
    sf = Conexiones.connect_SF(origen)
    conn_sql_server, cursor = Conexiones.connect_ETL_local_sql(origen)
    sf.session.headers.update({'Sforce-Transport-Settings': 'chunkSize=200'})
    cursor.fast_executemany = True
    
    # Campos a extraer (Se incluye AccountId para el reto de Einstein)
    fields = [
        'Id', 'Nombre_Completo__c', 'Title', 'Rol_con_ITESM__c',
        'LastActivityDate', 'LastReferencedDate', 'Nombre_RecordType__c',
        'OwnerId', 'AccountId'
        ]
    
    print("--- Iniciando limpieza de tabla local ---")
    try:
        cursor.execute("DELETE FROM Extraer_ContactosU4O")
        cursor.commit()
    except Exception as e:
        print("Error limpiando tabla Extraer_ContactosU4O:", str(e))
    
    # Lista para consolidar todos los IDs de contacto encontrados
    id_list_merged = []
    
    print("1. Buscando contactos en Actividades (WhoId)...")
    try:
        cursor.execute("SELECT DISTINCT WhoId FROM Extraer_ActividadesU4O WHERE WhoId IS NOT NULL")
        id_list_merged.extend([row[0] for row in cursor.fetchall()])
    except Exception as e:
        print("Error en paso 1:", str(e))
    
    print("2. Buscando contactos en Oportunidades (VEC_BusinessContact__c)...")
    try:
        cursor.execute(
            "SELECT DISTINCT VEC_BusinessContact__c FROM Extraer_OportunidadesU4O WHERE VEC_BusinessContact__c IS NOT NULL")
        id_list_merged.extend([row[0] for row in cursor.fetchall()])
    except Exception as e:
        print("Error en paso 2:", str(e))
    
    print("3. Buscando contactos vinculados a las Empresas (AccountId)...")
    try:
        # Obtenemos los IDs de las empresas tipo Business Organizations
        cursor.execute("SELECT DISTINCT Id FROM Extraer_EmpresasU4O WHERE Id IS NOT NULL")
        account_ids = [row[0] for row in cursor.fetchall()]
        
        if account_ids:
            # Procesamos las empresas en lotes para obtener sus contactos desde Salesforce
            batch_size_acc = 200
            for i in range(0, len(account_ids), batch_size_acc):
                batch_acc = account_ids[i:i + batch_size_acc]
                formatted_acc_ids = "','".join(batch_acc)
                
                query_contacts = f"SELECT Id FROM Contact WHERE AccountId IN ('{formatted_acc_ids}') AND IsDeleted = False"
                results = sf.query_all(query_contacts)['records']
                id_list_merged.extend([r['Id'] for r in results])
            
            print(f"   - Empresas procesadas: {len(account_ids)}")
    except Exception as e:
        print("Error en paso 3 (Enriquecimiento por AccountId):", str(e))
    
    # Limpieza de IDs duplicados y nulos
    unique_ids = list(set([i for i in id_list_merged if i is not None]))
    print(f"Total de contactos únicos a procesar: {len(unique_ids)}")
    
    print("--- Extrayendo información detallada de contactos ---")
    try:
        batch_size = 200
        for i in range(0, len(unique_ids), batch_size):
            batch = unique_ids[i:i + batch_size]
            formatted_ids = "','".join(batch)
            
            if formatted_ids:
                query = f"SELECT {','.join(fields)} FROM Contact WHERE Id IN ('{formatted_ids}')"
                response = sf.query_all(query)
                records = response['records']
                
                extracted_records = []
                for record in records:
                    # Normalización de datos
                    record['LastReferencedDate'] = normalizeDate(record['LastReferencedDate'])
                    # Aseguramos que los campos existan en el diccionario (Salesforce omite nulos)
                    row = [record.get(field) for field in fields]
                    extracted_records.append(row)
                
                # Inserción masiva
                placeholders = ','.join(['?' for _ in fields])
                insert_sql = f"INSERT INTO Extraer_ContactosU4O ({','.join(fields)}) VALUES ({placeholders})"
                cursor.executemany(insert_sql, extracted_records)
                cursor.commit()
                
                print(f"   - Procesados: {min(i + batch_size, len(unique_ids))} de {len(unique_ids)}")
    
    except Exception as e:
        print("Error en la extracción final de contactos:", str(e))
    
    finally:
        if cursor:
            cursor.close()
        if conn_sql_server:
            conn_sql_server.close()
        print('Extraer_ContactosU4O | Tiempo total:', datetime.now() - startTime)


if __name__ == "__main__":
    main(None)