from datetime import datetime
import Conexiones
import PMO_Mensajeria_Teams as pmo_teams_messenger
# Se importa el script específico para procesar los documentos fiscales (CSF).
# Este módulo contiene la lógica de OCR/Lectura de PDFs para extraer datos del SAT.
import PMO_Documentos_Datos_CSF as CSF


def oportunidad_ya_procesada(cursor, id_oportunidad):
    """
    Verifica si una oportunidad ya ha sido procesada anteriormente para evitar duplicados.

    Args:
        cursor: Cursor de la base de datos PMO.
        id_oportunidad (str): ID de Salesforce de la oportunidad.

    Returns:
        bool: True si ya existen documentos registrados, False si es nueva.
    """
    try:
        # Consulta de conteo simple para eficiencia
        check_query = "SELECT COUNT(1) FROM CRM_Documento_Proyectos WHERE id_de_oportunidad = ?"
        cursor.execute(check_query, (id_oportunidad,))
        # Si el conteo es mayor a 0, significa que ya fue procesada.
        return cursor.fetchone()[0] > 0
    except Exception as e:
        print(f"Error al verificar la existencia de la oportunidad {id_oportunidad}: {e}")
        # En caso de error, asumimos False para no bloquear, aunque podría generar intentos duplicados fallidos luego.
        return False


def obtener_documentos_de_oportunidad(sf_connection, oportunidad_id):
    """
    Obtiene los metadatos de los documentos asociados a una oportunidad en Salesforce.
    Realiza dos pasos:
    1. Busca registros en el objeto personalizado VEC_Documento_U4O__c.
    2. Usa los IDs de esos registros para buscar los archivos físicos en ContentDocumentLink.

    Args:
        sf_connection: Objeto de conexión a Salesforce (simple_salesforce).
        oportunidad_id (str): ID de la oportunidad.

    Returns:
        list: Lista de diccionarios con la info de cada documento.
    """
    if not oportunidad_id:
        print("El ID de Oportunidad no puede estar vacío.")
        return []
    
    print(f"  -> Consultando documentos en Salesforce para la oportunidad {oportunidad_id}...")
    try:
        # --- PASO 1: Obtener referencias del objeto de negocio (VEC_Documento_U4O__c) ---
        campo_lookup_oportunidad = 'VEC_Oportunidad__c'
        
        # Filtramos para no traer la 'Propuesta Inicial', ya que buscamos documentos de cierre.
        documento_u4o_query = f"""
        SELECT Id, CreatedById, RecordType.Name, RecordType.DeveloperName, RecordType.Description
        FROM VEC_Documento_U4O__c
        WHERE {campo_lookup_oportunidad} = '{oportunidad_id}'
        AND RecordType.DeveloperName != 'VEC_01_Propuesta_Inicial'
        """
        results_u4o = sf_connection.query(documento_u4o_query)
        
        # Mapeamos los detalles (Tipo de Registro, Creador) usando el ID como llave
        docs_u4o_details = {
            record['Id']: {
                'DocU4OCreatedById': record.get('CreatedById'),
                'RecordTypeName': (record.get('RecordType') or {}).get('Name'),
                'RecordTypeDeveloperName': (record.get('RecordType') or {}).get('DeveloperName'),
                'RecordTypeDescription': (record.get('RecordType') or {}).get('Description')
                } for record in results_u4o.get('records', [])
            }
        
        ids_documento_u4o = list(docs_u4o_details.keys())
        if not ids_documento_u4o:
            # Si no hay registros de negocio, no hay documentos adjuntos que buscar.
            return []
        
        # --- PASO 2: Obtener los archivos físicos (ContentDocument) ---
        # Formateamos los IDs para la cláusula IN de SOQL: 'id1','id2','id3'
        formatted_ids = "'" + "','".join(ids_documento_u4o) + "'"
        
        soql_query_files = f"""
        SELECT ContentDocument.Id, ContentDocument.Title,
               ContentDocument.LatestPublishedVersionId,
               ContentDocument.LatestPublishedVersion.FileType,
               ContentDocument.LatestPublishedVersion.CreatedDate, LinkedEntityId
        FROM ContentDocumentLink
        WHERE LinkedEntityId IN ({formatted_ids})
        """
        results_files = sf_connection.query(soql_query_files)
        
        documentos = []
        ids_procesados = set()  # Set para evitar duplicados si un archivo está linkeado múltiples veces
        
        for record in results_files.get('records', []):
            content_doc_id = record.get('ContentDocument', {}).get('Id')
            version_id = record.get('ContentDocument', {}).get('LatestPublishedVersionId')
            
            if version_id and content_doc_id not in ids_procesados:
                linked_id = record.get('LinkedEntityId')
                # Combinamos la info del archivo con la info del registro de negocio (details)
                details = docs_u4o_details.get(linked_id, {})
                doc = {
                    'ContentDocumentId': content_doc_id,
                    'LatestPublishedVersionId': version_id,
                    'Nombre': record.get('ContentDocument', {}).get('Title'),
                    'Tipo': record.get('ContentDocument', {}).get('LatestPublishedVersion', {}).get('FileType'),
                    'FechaCarga': record.get('ContentDocument', {}).get('LatestPublishedVersion', {}).get(
                        'CreatedDate'),
                    **details  # Desempaquetamos los detalles del tipo de registro
                    }
                documentos.append(doc)
                ids_procesados.add(content_doc_id)
        
        print(f"  -> Se encontraron {len(documentos)} archivo(s) únicos para la oportunidad {oportunidad_id}.")
        return documentos
    except Exception as e:
        print(f"Ocurrió un error al consultar Salesforce para la oportunidad {oportunidad_id}: {e}")
        return []


def insertar_documento(cursor, id_oportunidad, doc, fecha_procesamiento):
    """
    Inserta un documento en SQL Server (Tabla CRM_Documento_Proyectos).
    Maneja la conversión de fechas y evita duplicados por llave primaria.
    """
    try:
        # Conversión de fecha ISO 8601 de Salesforce a datetime de Python
        fecha_carga_str = doc['FechaCarga']
        fecha_obj = None
        if fecha_carga_str:
            try:
                fecha_obj = datetime.strptime(fecha_carga_str.split('.')[0], '%Y-%m-%dT%H:%M:%S')
            except (ValueError, TypeError):
                print(f"  -> ADVERTENCIA: Formato de fecha inválido ('{fecha_carga_str}'). Se insertará como nulo.")
        
        insert_query = """
        INSERT INTO CRM_Documento_Proyectos (
            id_de_oportunidad, ContentDocument_Id, ContentDocument_LatestPublishedVersionId,
            Title, FileType, CreatedDate, CreatedById, RecordTypeName,
            RecordTypeDeveloperName, RecordTypeDescription, BanderaLectura, FechaProcesamiento
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        valores = (
            id_oportunidad,
            doc['ContentDocumentId'],
            doc['LatestPublishedVersionId'],
            doc['Nombre'],
            doc['Tipo'],
            fecha_obj,
            doc['DocU4OCreatedById'],
            doc['RecordTypeName'] or '',
            doc['RecordTypeDeveloperName'] or '',
            doc['RecordTypeDescription'] or '',
            1,  # BanderaLectura inicializada en 1
            fecha_procesamiento
            )
        
        cursor.execute(insert_query, valores)
        return 1
    
    except Exception as e:
        # Si el documento ya existe (Primary Key), lo ignoramos silenciosamente pero retornamos 0
        if 'PRIMARY KEY constraint' in str(e):
            print(
                f"  -> OMITIDO: El documento '{doc['Nombre']}' (VersionID: {doc['LatestPublishedVersionId']}) ya existe.")
            return 0
        print(f"Error al procesar el documento {doc['LatestPublishedVersionId']} en SQL Server: {e}")
        return -1


def insertar_documento_default(cursor, id_oportunidad, fecha_procesamiento):
    """
    Inserta un registro de 'Riesgo' cuando una oportunidad ganada no tiene documentos adjuntos.
    Esto permite que el flujo continúe y se notifique la anomalía.
    """
    try:
        insert_query = """
        INSERT INTO CRM_Documento_Proyectos (
            id_de_oportunidad, ContentDocument_Id, ContentDocument_LatestPublishedVersionId,
            Title, FileType, CreatedDate, CreatedById, RecordTypeName,
            RecordTypeDeveloperName, RecordTypeDescription, BanderaLectura, FechaProcesamiento
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        # Valores 'hardcoded' para indicar el riesgo
        valores = (
            id_oportunidad, 'Riesgo', 'Riesgo', 'Aprobado sin propuesta por el líder',
            'Riesgo', datetime.now(), 'Riesgo', 'Riesgo', 'Riesgo', 'Riesgo', 1, fecha_procesamiento
            )
        cursor.execute(insert_query, valores)
        return 1
    except Exception as e:
        print(f"Error al insertar el registro por defecto para la oportunidad {id_oportunidad}: {e}")
        return -1


def insertar_registro_procesamiento(cursor, id_oportunidad):
    """
    Inserta en CRM_Procesamiento para marcar la oportunidad como 'Cerrada' y procesada.
    Esto evita que sea procesada de nuevo en el futuro.
    """
    try:
        insert_query = """
        INSERT INTO CRM_Procesamiento (
            id_de_oportunidad, BanderaEntrega, FechaSolicitud, TipoMovimiento,
            Email,  DataCRM, CampoCRM, FechaCierre
        ) VALUES (?, ?, ?, ?, NULL, NULL, NULL, NULL)
        """
        # BanderaEntrega = 1 indica completado. TipoMovimiento = 'Cierre'.
        valores = (id_oportunidad, 1, datetime.now(), 'Cierre')
        cursor.execute(insert_query, valores)
        return True
    except Exception as e:
        print(f"Error al insertar en CRM_Procesamiento para la oportunidad {id_oportunidad}: {e}")
        return False


def main(origen):
    """
    Orquestador principal del proceso.
    1. Obtiene oportunidades cerradas (regla de 7 días o última carga).
    2. Itera y extrae documentos de Salesforce.
    3. Invoca lógica especial para CSFs.
    4. Guarda en BD local y notifica.
    """
    start_time = datetime.now()
    conn_sindata, cursor_sindata = None, None
    conn_pmo, cursor_pmo = None, None
    
    try:
        print("Conectando a SIN_Data para obtener la lista de oportunidades...")
        conn_sindata, cursor_sindata = Conexiones.connect_SINDATA_local_sql(origen)
        
        # -------------------------------------------------------------------------
        # REGLA DE NEGOCIO: SELECCIÓN DE OPORTUNIDADES
        # Esta consulta define QUÉ se procesa. Combina dos criterios con UNION.
        # -------------------------------------------------------------------------
        query_oportunidades = """
        SELECT DISTINCT
            [MovimientoDiarios_AlteryxIdOportunidad],
            [MovimientoDiarios_Empresa],
            [MovimientoDiarios_NombreOportunidad],
            [MovimientoDiarios_PropietarioOportunidad],
            [MovimientoDiarios_Zona],
            CONVERT(date,[MovimientoDiarios_FechaCierreOportunidad],103) AS 'MovimientoDiarios_FechaCierreOportunidad'
        FROM [SIN_Data].[dbo].[Salesforce_MovimientoDiarios]
        WHERE [MovimientoDiarios_AlteryxIdOportunidad] IN (
            SELECT DISTINCT [MovimientoDiarios_AlteryxIdOportunidad] FROM (
                -- CRITERIO 1: Oportunidades 'Cerrada ganada' procesadas en la ÚLTIMA CARGA DE DATOS.
                -- Busca la fecha máxima de movimiento en la tabla.
                SELECT [MovimientoDiarios_AlteryxIdOportunidad]
                FROM [SIN_Data].[dbo].[Salesforce_MovimientoDiarios]
                WHERE [MovimientoDiarios_EtapaDetalle] = 'Cerrada ganada'
                AND CONVERT(date,[MovimientoDiarios_FechaCierreMovimiento],103) IN (
                    SELECT MAX(CONVERT(date,[MovimientoDiarios_FechaCierreMovimiento],103))
                    FROM [SIN_Data].[dbo].[Salesforce_MovimientoDiarios]
                )
                UNION
                -- CRITERIO 2: RED DE SEGURIDAD (Recuperación).
                -- Oportunidades 'Cerrada ganada' cuya fecha de cierre real fue en los ÚLTIMOS 7 DÍAS.
                -- Esto recupera cierres que pudieron no haberse procesado el día exacto.
                SELECT [MovimientoDiarios_AlteryxIdOportunidad]
                FROM [SIN_Data].[dbo].[Salesforce_MovimientoDiarios]
                WHERE [MovimientoDiarios_EtapaDetalle] = 'Cerrada ganada'
                AND CONVERT(date,[MovimientoDiarios_FechaCierreOportunidad],103) BETWEEN DATEADD(dd,-7, GETDATE()) AND GETDATE()
            ) AS SubQuery
        ) ORDER BY [MovimientoDiarios_FechaCierreOportunidad]
        """
        
        cursor_sindata.execute(query_oportunidades)
        oportunidades_a_procesar = [row for row in cursor_sindata.fetchall() if row[0]]
        
        if not oportunidades_a_procesar:
            print("No se encontraron oportunidades 'Cerrada ganada' para procesar.")
            return
        
        print(f"Se encontraron {len(oportunidades_a_procesar)} oportunidades únicas para procesar.")
        
        print("Conectando a Salesforce y a la base de datos PMO...")
        sf = Conexiones.connect_SF(origen)
        conn_pmo, cursor_pmo = Conexiones.connect_PMO_saas_sql(origen)
        
        total_documentos_insertados = 0
        oportunidades_procesadas_con_exito = 0
        oportunidades_notificar = []
        
        # Bucle principal de procesamiento
        for i, (opp_id, company_name, opp_name, asesor, zona, _) in enumerate(oportunidades_a_procesar):
            
            # Verificación de duplicados antes de procesar
            if oportunidad_ya_procesada(cursor_pmo, opp_id):
                # print(f"  -> OMITIDA: La oportunidad {opp_id} ya tiene documentos registrados. Saltando.")
                continue
            
            # Obtención de documentos desde Salesforce
            lista_de_documentos = obtener_documentos_de_oportunidad(sf, opp_id)
            
            documentos_insertados_por_opp = 0
            documentos_para_notificar = lista_de_documentos.copy()
            
            if not lista_de_documentos:
                # Caso: Riesgo (Sin documentos)
                print(f"  -> No se encontraron documentos en Salesforce.")
                documentos_insertados_por_opp = insertar_documento_default(cursor_pmo, opp_id, start_time)
                if documentos_insertados_por_opp > 0:
                    documentos_para_notificar = [
                        {"Nombre": "¡¡RIESGO!!: Aprobado sin documentos por el líder", "Tipo": ""}]
            else:
                # Caso: Con documentos
                for doc in lista_de_documentos:
                    # LOGICA ESPECIAL: Si es una Constancia de Situación Fiscal (CSF)
                    if "CSF" in doc.get('Nombre', ''):
                        print(f"  -> DETECTADO DOCUMENTO CSF: '{doc['Nombre']}'. Invocando proceso de datos.")
                        # Se llama al módulo externo para leer el PDF y extraer datos
                        CSF.main(
                            ContentDocument_LatestPublishedVersionId=doc['LatestPublishedVersionId'],
                            opp_id=opp_id,
                            company_name=company_name,
                            sf_connection=sf,
                            conn_pmo=conn_pmo,
                            fecha_procesamiento=start_time
                            )
                    
                    insertados = insertar_documento(cursor_pmo, opp_id, doc, start_time)
                    documentos_insertados_por_opp += insertados
            
            # Si se logró insertar algo (documento real o riesgo), registramos el cierre
            if documentos_insertados_por_opp > 0:
                if insertar_registro_procesamiento(cursor_pmo, opp_id):
                    # COMMIT DE TRANSACCIÓN: Solo confirmamos si el registro de procesamiento (docs + registro) salió bien
                    conn_pmo.commit()
                    total_documentos_insertados += documentos_insertados_por_opp
                    oportunidades_procesadas_con_exito += 1
                    
                    # Agregamos a la cola de notificaciones
                    oportunidades_notificar.append({
                        "opp_id": opp_id, "company_name": company_name, "opp_name": opp_name,
                        "asesor": asesor, "zona": zona, "document_list": documentos_para_notificar
                        })
                else:
                    # ROLLBACK: Si falla el registro de control, deshacemos la inserción de documentos
                    conn_pmo.rollback()
                    print(
                        f"  -> CAMBIOS REVERTIDOS para la oportunidad {opp_id} debido a un error en el registro de procesamiento.")
        
        # Envío de notificaciones consolidadas al final del lote
        if oportunidades_notificar:
            print(f"\n--- Enviando notificación consolidada para {len(oportunidades_notificar)} oportunidades ---")
            pmo_teams_messenger.enviar_notificacion_consolidada(
                title=f"Resumen de Cierre de Oportunidades - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                oportunidades_procesadas=oportunidades_notificar
                )
        
        print(f"\n--- ✅ Proceso global completado ---")
        print(f"Se insertaron un total de {total_documentos_insertados} nuevos registros de documentos.")
        print(f"Se procesaron con éxito {oportunidades_procesadas_con_exito} nuevas oportunidades.")
    
    except Exception as e:
        print(f"\n--- ❌ Error en el proceso principal ---: {e}")
        if conn_pmo:
            conn_pmo.rollback()
            print("Se ha revertido la última transacción en la base de datos PMO.")
    
    finally:
        # Limpieza y cierre seguro de conexiones
        if cursor_sindata: cursor_sindata.close()
        if conn_sindata: conn_sindata.close(); print("\nConexión a SIN_Data cerrada.")
        if cursor_pmo: cursor_pmo.close()
        if conn_pmo: conn_pmo.close(); print("Conexión a PMO_saas_sql cerrada.")
        
        end_time = datetime.now()
        print(f"Duración total del proceso: {end_time - start_time}")


if __name__ == "__main__":
    main(None)