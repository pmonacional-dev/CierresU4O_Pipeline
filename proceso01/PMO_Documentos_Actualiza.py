from datetime import datetime
import Conexiones
import PMO_Mensajeria_Teams as pmo_teams_messenger
# Se importa el script para procesar los documentos CSF.
import PMO_Documentos_Datos_CSF as CSF



def obtener_info_oportunidad(sf_connection, oportunidad_id):
    """
    Obtiene el nombre de la oportunidad y el nombre de la cuenta (empresa)
    desde Salesforce.
    """
    try:
        query = f"SELECT Name, Account.Name FROM Opportunity WHERE Id = '{oportunidad_id}'"
        results = sf_connection.query(query)
        if results.get('totalSize') > 0:
            record = results['records'][0]
            return {
                'OppName': record.get('Name'),
                'CompanyName': (record.get('Account') or {}).get('Name', 'No especificada')
                }
        return {'OppName': 'No encontrado', 'CompanyName': 'No encontrada'}
    except Exception as e:
        print(f"Error al obtener información de la oportunidad {oportunidad_id}: {e}")
        return {'OppName': 'Error', 'CompanyName': 'Error'}


def obtener_documentos_de_oportunidad(sf_connection, oportunidad_id):
    """
    Extrae los archivos adjuntos a los registros de VEC_Documento_U4O__c
    que están vinculados a un ID de Oportunidad específico.
    """
    if not oportunidad_id:
        print("El ID de Oportunidad no puede estar vacío.")
        return []
    
    print(f"  -> Buscando documentos para Oportunidad: {oportunidad_id}...")
    try:
        campo_lookup_oportunidad = 'VEC_Oportunidad__c'
        documento_u4o_query = f"""
        SELECT Id, CreatedById, RecordType.Name, RecordType.DeveloperName, RecordType.Description
        FROM VEC_Documento_U4O__c
        WHERE {campo_lookup_oportunidad} = '{oportunidad_id}'
        AND RecordType.DeveloperName != 'VEC_01_Propuesta_Inicial'
        """
        results_u4o = sf_connection.query(documento_u4o_query)
        
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
            return []
        
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
        ids_procesados = set()
        for record in results_files.get('records', []):
            content_doc_id = record.get('ContentDocument', {}).get('Id')
            version_id = record.get('ContentDocument', {}).get('LatestPublishedVersionId')
            
            if version_id and content_doc_id not in ids_procesados:
                linked_id = record.get('LinkedEntityId')
                details = docs_u4o_details.get(linked_id, {})
                doc = {
                    'ContentDocumentId': content_doc_id,
                    'LatestPublishedVersionId': version_id,
                    'Id': version_id,
                    'Nombre': record.get('ContentDocument', {}).get('Title'),
                    'Tipo': record.get('ContentDocument', {}).get('LatestPublishedVersion', {}).get('FileType'),
                    'FechaCarga': record.get('ContentDocument', {}).get('LatestPublishedVersion', {}).get(
                        'CreatedDate'),
                    **details
                    }
                documentos.append(doc)
                ids_procesados.add(content_doc_id)
        
        print(f"  -> Se encontraron {len(documentos)} archivo(s) únicos para la oportunidad {oportunidad_id}.")
        return documentos
    
    except Exception as e:
        print(f"Ocurrió un error al consultar Salesforce para la oportunidad {oportunidad_id}: {e}")
        return []


def desactivar_documentos_anteriores(cursor, id_oportunidad):
    """
    Actualiza la BanderaLectura a 0 para todos los documentos existentes de una oportunidad.
    """
    try:
        update_query = "UPDATE CRM_Documento_Proyectos SET BanderaLectura = 0 WHERE id_de_oportunidad = ? AND BanderaLectura = 1"
        cursor.execute(update_query, (id_oportunidad,))
        print(f"  -> Se desactivaron {cursor.rowcount} documento(s) anterior(es) para la oportunidad {id_oportunidad}.")
        return True
    except Exception as e:
        print(f"Error al desactivar documentos anteriores para la oportunidad {id_oportunidad}: {e}")
        return False


def insertar_documento(cursor, id_oportunidad, doc, fecha_procesamiento):
    """
    Inserta un nuevo registro de documento en la tabla CRM_Documento_Proyectos.
    """
    try:
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
            1,
            fecha_procesamiento
            )
        
        cursor.execute(insert_query, valores)
        print(f"  -> INSERTADO: El documento '{doc['Nombre']}' (VersionID: {doc['LatestPublishedVersionId']}).")
        return 1
    
    except Exception as e:
        if 'PRIMARY KEY constraint' in str(e):
            print(
                f"  -> OMITIDO: El documento '{doc['Nombre']}' (VersionID: {doc['LatestPublishedVersionId']}) ya existe.")
            return 0
        print(f"Error al procesar el documento {doc['LatestPublishedVersionId']} en SQL Server: {e}")
        return -1


def insertar_documento_default(cursor, id_oportunidad, fecha_procesamiento):
    """
    Inserta un registro por defecto cuando no se encuentran documentos.
    """
    try:
        insert_query = """
        INSERT INTO CRM_Documento_Proyectos (
            id_de_oportunidad, ContentDocument_Id, ContentDocument_LatestPublishedVersionId,
            Title, FileType, CreatedDate, CreatedById, RecordTypeName,
            RecordTypeDeveloperName, RecordTypeDescription, BanderaLectura, FechaProcesamiento
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        valores = (
            id_oportunidad,
            'Riesgo',
            'Riesgo',
            '¡¡RIESGO!!: Aprobado sin documentos por el líder',
            'Riesgo',
            datetime.now(),
            'Riesgo',
            'Riesgo',
            'Riesgo',
            'Riesgo',
            1,
            fecha_procesamiento
            )
        cursor.execute(insert_query, valores)
        print("  -> INSERTADO: Registro por defecto 'Aprobado sin propuesta'.")
        return 1
    except Exception as e:
        print(f"Error al insertar el registro por defecto para la oportunidad {id_oportunidad}: {e}")
        return -1


def actualizar_registro_procesamiento(cursor, id_oportunidad):
    """
    Obtiene el email del solicitante y actualiza el registro de procesamiento.
    Devuelve el email para ser usado en la notificación.
    """
    email_solicitante = None
    try:
        email_query = "SELECT Email FROM CRM_Procesamiento WHERE id_de_oportunidad = ? AND TipoMovimiento = 'Actualiza_Documento' AND BanderaEntrega = 0"
        cursor.execute(email_query, (id_oportunidad,))
        result = cursor.fetchone()
        
        if result and result[0]:
            email_solicitante = result[0]
        else:
            print(f"  -> No se encontró email para la oportunidad {id_oportunidad}.")
        
        update_query = "UPDATE CRM_Procesamiento SET BanderaEntrega = 1, FechaCierre = ? WHERE id_de_oportunidad = ? AND TipoMovimiento = 'Actualiza_Documento' AND BanderaEntrega = 0"
        valores = (datetime.now(), id_oportunidad)
        cursor.execute(update_query, valores)
        
        if cursor.rowcount > 0:
            print(f"  -> REGISTRO ACTUALIZADO: BanderaEntrega=1 para la oportunidad {id_oportunidad}.")
            return email_solicitante
        else:
            print(
                f"  -> ADVERTENCIA: No se encontró un registro pendiente para actualizar para la oportunidad {id_oportunidad}.")
            return None
    
    except Exception as e:
        print(f"Error al actualizar CRM_Procesamiento para la oportunidad {id_oportunidad}: {e}")
        return None


def main(origen):
    """
    Función principal que orquesta todo el proceso de actualización.
    """
    start_time = datetime.now()
    conn_pmo, cursor_pmo = None, None
    
    try:
        print("Conectando a la base de datos PMO para obtener la lista de oportunidades a actualizar...")
        conn_pmo, cursor_pmo = Conexiones.connect_PMO_saas_sql(origen)
        
        if not conn_pmo or not cursor_pmo:
            print("--- ❌ Error Crítico: No se pudo establecer conexión con la base de datos PMO. ---")
            return
        
        query_oportunidades = "SELECT [id_de_oportunidad] FROM [dbo].[CRM_Procesamiento] WHERE [BanderaEntrega] = 0 AND [TipoMovimiento] = 'Actualiza_Documento'"
        cursor_pmo.execute(query_oportunidades)
        oportunidades_ids = {row[0] for row in cursor_pmo.fetchall() if row[0]}
        
        if not oportunidades_ids:
            print("No se encontraron oportunidades con 'Actualiza_Documento' para procesar.")
            return
        
        print(f"Se encontraron {len(oportunidades_ids)} oportunidades únicas para procesar.")
        
        print("Conectando a Salesforce...")
        sf = Conexiones.connect_SF(origen)
        
        notificaciones_por_usuario = {}
        
        for i, opp_id in enumerate(oportunidades_ids):
            print(f"\n--- Procesando Oportunidad {i + 1}/{len(oportunidades_ids)} (ID: {opp_id}) ---")
            error_en_oportunidad = False
            
            # <<< INICIO DE LA MODIFICACIÓN >>>
            # Se obtiene la información de la oportunidad una sola vez al inicio del bucle.
            info_opp = obtener_info_oportunidad(sf, opp_id)
            # <<< FIN DE LA MODIFICACIÓN >>>
            
            if not desactivar_documentos_anteriores(cursor_pmo, opp_id):
                conn_pmo.rollback()
                print(f"Se revirtieron los cambios para la oportunidad {opp_id} por error al desactivar.")
                continue
            
            lista_de_documentos = obtener_documentos_de_oportunidad(sf, opp_id)
            documentos_para_notificar = []
            
            if not lista_de_documentos:
                print(f"  -> No se encontraron documentos nuevos en Salesforce.")
                insertados = insertar_documento_default(cursor_pmo, opp_id, start_time)
                if insertados == -1:
                    error_en_oportunidad = True
                else:
                    documentos_para_notificar.append(
                        {'Nombre': '¡¡RIESGO!!: Aprobado sin documentos por el líder', 'Tipo': ''})
            else:
                for doc in lista_de_documentos:
                    # Se verifica si el nombre del documento contiene "CSF" para procesarlo de forma especial.
                    if "CSF" in doc.get('Nombre', ''):
                        print(f"  -> DETECTADO DOCUMENTO CSF: '{doc['Nombre']}'. Invocando proceso de datos.")
                        # Se llama al main de PMO_Documentos_Datos_CSF pasando la conexión 'sf' existente.
                        CSF.main(
                            ContentDocument_LatestPublishedVersionId=doc['LatestPublishedVersionId'],
                            opp_id=opp_id,
                            company_name=info_opp.get('CompanyName'),
                            sf_connection=sf,
                            conn_pmo=conn_pmo,
                            fecha_procesamiento=start_time
                        )
                    
                    insertados = insertar_documento(cursor_pmo, opp_id, doc, start_time)
                    if insertados == -1:
                        error_en_oportunidad = True
                        break
                    elif insertados > 0:
                        documentos_para_notificar.append(doc)
            
            if error_en_oportunidad:
                conn_pmo.rollback()
                print(f"Se revirtieron los cambios para la oportunidad {opp_id} por error al insertar documentos.")
                continue
            
            email_a_notificar = actualizar_registro_procesamiento(cursor_pmo, opp_id)
            
            if email_a_notificar:
                conn_pmo.commit()
                print(f"Se confirmaron los cambios para la oportunidad {opp_id}.")
                
                if email_a_notificar not in notificaciones_por_usuario:
                    notificaciones_por_usuario[email_a_notificar] = []
                
                notificaciones_por_usuario[email_a_notificar].append({
                    "opp_id": opp_id,
                    "company_name": info_opp.get('CompanyName'),
                    "opp_name": info_opp.get('OppName'),
                    "document_list": documentos_para_notificar
                    })
            else:
                conn_pmo.rollback()
                print(f"Se revirtieron los cambios para la oportunidad {opp_id} por error al actualizar el estado.")
        
        if notificaciones_por_usuario:
            print(f"\n--- Enviando notificaciones consolidadas por usuario ---")
            for email, oportunidades in notificaciones_por_usuario.items():
                pmo_teams_messenger.enviar_notificacion_consolidada(
                        title=f"Resumen de Actualización de Documentos",
                        oportunidades_procesadas=oportunidades,
                        cadena_emails=email
                )
        
        print(f"\n--- ✅ Proceso global completado ---")
    
    except Exception as e:
        print(f"\n--- ❌ Error en el proceso principal ---: {e}")
        if conn_pmo:
            conn_pmo.rollback()
            print("Se ha revertido la última transacción en la base de datos PMO.")
    
    finally:
        if cursor_pmo: cursor_pmo.close()
        if conn_pmo: conn_pmo.close(); print("\nConexión a PMO_saas_sql cerrada.")
        
        end_time = datetime.now()
        print(f"Duración total del proceso: {end_time - start_time}")


if __name__ == "__main__":
    main(None)
    # main("Erik")
