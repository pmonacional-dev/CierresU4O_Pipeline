import io
import re
import PyPDF2  # python -m pip install PyPDF2 // Libreria para lectura de pdf
from satcfdi import \
    csf  # python -m pip install satcfdi // Libreria para extracción de datos SAT a partir de idCIF y RFC
from urllib.parse import urlparse
import datetime  # Importamos datetime para el manejo de fechas


def extraer_credenciales_pdf(texto_completo):
    """
    Analiza el texto del PDF para encontrar únicamente el RFC y el idCIF.
    """
    rfc_match = re.search(r"RFC:\s*([A-Z0-9&Ñ]{12,13})", texto_completo, re.IGNORECASE)
    idcif_match = re.search(r"idCIF:\s*([0-9]+)", texto_completo, re.IGNORECASE)
    
    rfc = rfc_match.group(1) if rfc_match else None
    idcif = idcif_match.group(1) if idcif_match else None
    
    if rfc and idcif:
        return {'rfc': rfc, 'idcif': idcif}
    
    return None


def desactivar_registros_anteriores(cursor, opp_id, company_name, idcif, rfc):
    """
    Pone en 0 la BanderaLectura de registros que coincidan con los criterios.
    """
    try:
        print("  -> Desactivando registros CSF anteriores...")
        update_query = """
            UPDATE CRM_Documento_CSF
            SET BanderaLectura = 0
            WHERE id_de_oportunidad = ?
              AND company_name = ?
              AND idCIF = ?
              AND RFC = ?
              AND BanderaLectura = 1
        """
        cursor.execute(update_query, (opp_id, company_name, idcif, rfc))
        print(f"  -> {cursor.rowcount} registro(s) anterior(es) desactivado(s).")
        return True
    except Exception as e:
        print(f"Error al desactivar registros CSF anteriores: {e}")
        return False


def insertar_datos_csf(cursor, opp_id, company_name, idcif, rfc, datos_sat, fecha_procesamiento):
    """
    Inserta un nuevo registro con los datos extraídos del SAT en la tabla CRM_Documento_CSF.
    """
    try:
        print("  -> Insertando nuevo registro de datos CSF...")
        insert_query = """
            INSERT INTO CRM_Documento_CSF (
                FechaProcesamiento, id_de_oportunidad, company_name, idCIF, RFC,
                RazonSocial, RegimenCapital, FechaConstitucion, FechaInicioOperaciones,
                SituacionContribuyente, FechaUltimoCambio, EntidadFederativa, Municipio,
                Colonia, TipoVialidad, NombreVialidad, NumExterior, NumInterior,
                CodigoPostal, Email, AL, RegimenFiscal, FechaAlta, BanderaLectura
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """
        
        # Mapeo de datos para una inserción más segura usando .get()
        # El pre-procesamiento en la función main asegura que 'RegimenFiscal' y 'Fecha de alta'
        # ya existen en el diccionario principal 'datos_sat'.
        valores = (
            fecha_procesamiento,
            opp_id,
            company_name,
            idcif,
            rfc,
            datos_sat.get('Denominación o Razón Social'),
            datos_sat.get('Régimen de capital'),
            datos_sat.get('Fecha de constitución'),
            datos_sat.get('Fecha de Inicio de operaciones'),
            datos_sat.get('Situación del contribuyente'),
            datos_sat.get('Fecha del último cambio de situación'),
            datos_sat.get('Entidad Federativa'),
            datos_sat.get('Municipio o delegación'),
            datos_sat.get('Colonia'),
            datos_sat.get('Tipo de vialidad'),
            datos_sat.get('Nombre de la vialidad'),
            datos_sat.get('Número exterior'),
            datos_sat.get('Número interior'),
            datos_sat.get('CP'),
            datos_sat.get('Correo electrónico'),
            datos_sat.get('AL'),
            datos_sat.get('RegimenFiscal'),
            datos_sat.get('Fecha de alta')
            )
        
        cursor.execute(insert_query, valores)
        print("  -> Nuevo registro CSF insertado exitosamente.")
        return True
    except Exception as e:
        print(f"Error al insertar el registro CSF: {e}")
        return False


def main(ContentDocument_LatestPublishedVersionId, opp_id, company_name, sf_connection, conn_pmo, fecha_procesamiento):
    """
    Descarga un PDF, extrae datos del SAT y los guarda en la base de datos PMO.
    """
    cursor_pmo = None
    try:
        sf = sf_connection
        if not sf:
            print("Error: La conexión a Salesforce proporcionada no es válida.")
            return
        
        print(f"Obteniendo metadatos del ContentVersion ID: {ContentDocument_LatestPublishedVersionId}...")
        content_version = sf.ContentVersion.get(ContentDocument_LatestPublishedVersionId)
        parsed_url = urlparse(sf.base_url)
        hostname = f"{parsed_url.scheme}://{parsed_url.netloc}"
        url_contenido = f"{hostname}{content_version['VersionData']}"
        
        print("Descargando contenido del PDF...")
        respuesta = sf.session.get(url_contenido, headers=sf.headers)
        respuesta.raise_for_status()
        contenido_pdf_binario = respuesta.content
        print("¡Descarga completada!")
        
        credenciales = None
        if contenido_pdf_binario:
            print("Extrayendo texto del PDF...")
            texto_extraido = ""
            with io.BytesIO(contenido_pdf_binario) as pdf_en_memoria:
                lector_pdf = PyPDF2.PdfReader(pdf_en_memoria)
                for pagina in lector_pdf.pages:
                    texto_pagina = pagina.extract_text()
                    if texto_pagina:
                        texto_extraido += texto_pagina + "\n"
            
            if texto_extraido.strip():
                print("Buscando RFC e idCIF...")
                credenciales = extraer_credenciales_pdf(texto_extraido)
        
        if not credenciales:
            print("Error: No se pudo encontrar el RFC o el idCIF en el PDF.")
            return
        
        print(f"RFC encontrado: {credenciales['rfc']}, idCIF encontrado: {credenciales['idcif']}")
        
        print("Consultando datos en el servicio del SAT...")
        datos_sat = csf.retrieve(rfc=credenciales['rfc'], id_cif=credenciales['idcif'])
        print("¡Consulta al SAT exitosa!")
        print(datos_sat)
        
        # <<< INICIO DE LA MODIFICACIÓN >>>
        # Se procesa y aplana la información de los regímenes fiscales para obtener el más reciente.
        regimen_fiscal_final = None
        fecha_alta_final = None
        
        if datos_sat and 'Regimenes' in datos_sat and datos_sat['Regimenes']:
            lista_regimenes = datos_sat['Regimenes']
            
            # 1. Encontrar el régimen con la fecha de alta más reciente usando max()
            # Se usa .get('Fecha de alta', datetime.date.min) para evitar errores si la clave no existe
            regimen_mas_reciente = max(lista_regimenes, key=lambda r: r.get('Fecha de alta', datetime.date.min))
            
            # 2. Extraer los datos del régimen más reciente
            fecha_alta_final = regimen_mas_reciente.get('Fecha de alta')
            regimen_objeto = regimen_mas_reciente.get('RegimenFiscal')
            
            # 3. Convertir el objeto Code a string para la BD
            if regimen_objeto:
                try:
                    # Intenta acceder al atributo .description, que es más descriptivo
                    regimen_fiscal_final = regimen_objeto.description
                except AttributeError:
                    # Si falla, lo trata como una tupla y toma el segundo elemento
                    regimen_fiscal_final = str(regimen_objeto[1]) if len(regimen_objeto) > 1 else str(regimen_objeto)
        
        # 4. "Aplanar" los datos, agregándolos al diccionario principal para la inserción.
        datos_sat['RegimenFiscal'] = regimen_fiscal_final
        datos_sat['Fecha de alta'] = fecha_alta_final
        # <<< FIN DE LA MODIFICACIÓN >>>
        
        if datos_sat:
            print("\n--- Iniciando operaciones en la base de datos PMO ---")
            cursor_pmo = conn_pmo.cursor()
            
            # Acción 1: Desactivar registros anteriores
            if not desactivar_registros_anteriores(cursor_pmo, opp_id, company_name, credenciales['idcif'],
                                                   credenciales['rfc']):
                raise Exception("Fallo al desactivar registros. Reversando cambios.")
            
            # Acción 2: Insertar nuevo registro
            if not insertar_datos_csf(cursor_pmo, opp_id, company_name, credenciales['idcif'], credenciales['rfc'],
                                      datos_sat, fecha_procesamiento):
                raise Exception("Fallo al insertar nuevo registro. Reversando cambios.")
            
            # NOTA: El commit se debe manejar en el script principal que llama a esta función.
            print("--- Operaciones en BD finalizadas exitosamente ---")
        
        else:
            print("\nNo se pudieron obtener los datos estructurados del SAT para guardar en la BD.")
    
    except Exception as e:
        print(f"Ocurrió un error en el proceso CSF: {e}")
        # NOTA: El rollback también se debe manejar en el script principal.
    
    finally:
        if cursor_pmo:
            cursor_pmo.close()


if __name__ == "__main__":
    print("Este script no está diseñado para ejecutarse directamente sin parámetros.")
