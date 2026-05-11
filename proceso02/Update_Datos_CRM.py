# -*- coding: utf-8 -*-
"""
Created on Mon Mar  4 19:05:02 2024

@author: Antonio Guerrero Juárez
"""

import pyodbc
import pandas as pd
import sys
import os
sys.path.append("Campus.py")
from Conexion_SQL import crear_conexion_sql
from Conexion_SalesForce import connect_to_salesforce
from sqlalchemy import create_engine
from Teams_Messages import TeamsWebhook
from datetime import datetime

# Rutas base relativas al script
_BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
_OUTPUT_DIR = os.path.join(_BASE_DIR, "output")
_LOGS_DIR   = os.path.join(_BASE_DIR, "logs")

# <<< NUEVO: modo prueba >>>
MODO_PRUEBA = False  # True, Cambia a False cuando ya quieras que actualice en SQL

# <<< NUEVO: usuario que se guardará en CRM_Actualizaciones_Log >>>
USUARIO_PROCESO = "script_update_ceco_codigo_servicio"

# <<< NUEVO: helper para insertar en CRM_Actualizaciones_Log >>>
def insertar_log_actualizacion(cursor, id_crm, campo_sql, valor_anterior, valor_nuevo):
    """
    Inserta un registro en CRM_Actualizaciones_Log.
    campo_sql será el nombre del campo en Datos_CRM: 'orden_interna' o 'codigo_servicio'.
    """
    insert_sql = """
        INSERT INTO CRM_Actualizaciones_Log (
            id_crm,
            campo_actualizado,
            valor_anterior,
            valor_nuevo,
            notificacion_enviada,
            usuario_proceso
        )
        VALUES (?, ?, ?, ?, 0, ?)
    """
    # Convertimos a string por seguridad, permitiendo NULL
    va = None if valor_anterior is None else str(valor_anterior)
    vn = None if valor_nuevo is None else str(valor_nuevo)

    # En modo prueba NO insertamos en SQL
    if MODO_PRUEBA:
        return

    cursor.execute(insert_sql, (id_crm, campo_sql, va, vn, USUARIO_PROCESO))

# <<< NUEVO: helper para guardar log TXT en carpeta logs >>>
def guardar_log_txt(campo_sql, registros_actualizados):
    """
    Genera un archivo TXT en la carpeta 'logs' con el detalle de las actualizaciones:
    - id_crm
    - campo actualizado
    - valor anterior
    - valor nuevo
    - fecha_cambio
    """
    if not registros_actualizados:
        return

    # Aseguramos que exista la carpeta 'logs'
    carpeta_logs = _LOGS_DIR
    os.makedirs(carpeta_logs, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"update_{campo_sql}_{timestamp}.txt"
    ruta_completa = os.path.join(carpeta_logs, nombre_archivo)

    with open(ruta_completa, "w", encoding="utf-8") as f:
        f.write(f"LOG DE ACTUALIZACIONES - CAMPO: {campo_sql}\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total de registros {'que se habrían actualizado' if MODO_PRUEBA else 'actualizados'}: {len(registros_actualizados)}\n\n")

        for reg in registros_actualizados:
            f.write(f"id_crm: {reg['id_crm']}\n")
            f.write(f"  campo           : {campo_sql}\n")
            f.write(f"  valor_anterior  : {reg.get('valor_anterior')}\n")
            f.write(f"  valor_nuevo     : {reg.get(campo_sql)}\n")
            f.write(f"  fecha_cambio    : {reg.get('fecha_cambio')}\n")
            f.write("-" * 80 + "\n")

    print(f"[INFO] Log TXT generado: {ruta_completa}")

def obtener_datos(cursor, opcion):
    
    """
    Flujos para opción:
        1 -> orden interna
        2 -> código de servicio
    """
    
    # Diccionario de opciones
    opciones = {
        1: ('orden_interna', 'VEC_CeCo__c'),
        2: ('codigo_servicio', 'VEC_Codigo_de_Servicio_del__c')
    }
    
    if opcion not in opciones:
        print("Opción inválida. El programa se detendrá.")
        sys.exit()
    
    condicionWhere, condicionSelect = opciones[opcion]

    # Ejecutamos la consulta.
    cursor.execute(f"""
        SELECT id_crm
        FROM Datos_CRM
        WHERE {condicionWhere} = 'Sin información en CRM'
    """)

    # Recogemos los resultados.
    registros = cursor.fetchall()
    
    if not registros:
        print("No se encontraron registros en la consulta. El programa se detendrá.")
        sys.exit()
    
    # Obtener los nombres de las columnas.
    id_crm_list = [registro[0] for registro in registros]

    # Convertir los ID de CRM en una cadena separada por comas
    id_crm_str = ','.join([f"'{id_oportunidad_CRM}'" for id_oportunidad_CRM in id_crm_list])
        
    # Realizar una sola consulta a Salesforce con todos los identificadores
    soql_query = f"""
        SELECT 
            Id,
            {condicionSelect}
        FROM Opportunity
        WHERE Id IN ({id_crm_str})
    """
    # Establecer conexión con Salesforce
    sf = connect_to_salesforce()
    
    # Ejecutar la consulta SOQL en Salesforce
    result = sf.query_all(soql_query)
    
    # Verificar si hay registros en la consulta SOQL
    if not result['records']:
        print("No se encontraron registros en Salesforce. El programa se detendrá.")
        sys.exit()
        
    return pd.DataFrame(result['records'])


def actualizar_datos_crm(cursor, df_opportunity, opcion):
    
    """
    Flujos para opción:
        1 -> orden interna (VEC_CeCo__c)
        2 -> código de servicio (VEC_Codigo_de_Servicio_del__c)
    """
    
    # Diccionario de opciones
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    opciones = {
        1: ('VEC_CeCo__c', 'orden_interna', os.path.join(_OUTPUT_DIR, 'cambios_orden_interna.xlsx')),
        2: ('VEC_Codigo_de_Servicio_del__c', 'codigo_servicio', os.path.join(_OUTPUT_DIR, 'cambios_codigo_servicio.xlsx'))
    }
    
    if opcion not in opciones:
        print("Opción inválida. El programa se detendrá.")
        sys.exit()
    
    campo_salesforce, campo_sql, nombre_archivo = opciones[opcion]
    
    # Filtrar registros que no tienen información en el campo correspondiente de Salesforce
    df_opportunity = df_opportunity[df_opportunity[campo_salesforce].notnull()]

    # DataFrame para acumular los registros actualizados
    registros_actualizados = []

    # Iterar sobre los registros de Salesforce y actualizar la base de datos SQL
    for index, row in df_opportunity.iterrows():
        id_crm = row['Id']
        valor_campo_nuevo = row[campo_salesforce]

        # <<< NUEVO: obtener el valor anterior desde Datos_CRM >>>
        cursor.execute(f"""
            SELECT {campo_sql}
            FROM Datos_CRM
            WHERE id_crm = ?
        """, (id_crm,))
        row_db = cursor.fetchone()

        if not row_db:
            # Si por alguna razón el id_crm ya no existe en Datos_CRM, lo saltamos
            print(f"[WARN] id_crm={id_crm} no se encontró en Datos_CRM. Se omite.")
            continue

        valor_campo_anterior = row_db[0]

        # <<< NUEVO: evitar actualizar si el valor ya es el mismo >>>
        if valor_campo_anterior == valor_campo_nuevo:
            # Nada que hacer, ya está actualizado
            continue
        
        # Ejecutar la actualización en la base de datos SQL (solo si NO es modo prueba)
        if not MODO_PRUEBA:
            cursor.execute(f"""
                UPDATE Datos_CRM
                SET {campo_sql} = ?
                WHERE id_crm = ?
            """, (valor_campo_nuevo, id_crm))

        # <<< NUEVO: insertar el log de actualización >>>
        insertar_log_actualizacion(
            cursor=cursor,
            id_crm=id_crm,
            campo_sql=campo_sql,
            valor_anterior=valor_campo_anterior,
            valor_nuevo=valor_campo_nuevo
        )

        # Acumular los registros actualizados
        registros_actualizados.append({
            'id_crm': id_crm,
            campo_sql: valor_campo_nuevo,
            'valor_anterior': valor_campo_anterior
        })

    # Convertir la lista de registros actualizados en un DataFrame
    df_actualizados = pd.DataFrame(registros_actualizados)
    
    # Añadir columna de fecha de cambio
    if not df_actualizados.empty:
        df_actualizados['fecha_cambio'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # También agregamos la fecha_cambio al dict para el TXT
        for i, reg in enumerate(registros_actualizados):
            registros_actualizados[i]['fecha_cambio'] = df_actualizados.loc[i, 'fecha_cambio']
    
    # <<< NUEVO: generar TXT en carpeta logs >>>
    guardar_log_txt(campo_sql, registros_actualizados)
    
    # Verificar si el archivo ya existe
    if os.path.exists(nombre_archivo):
        # Si el archivo existe, cargar el contenido existente
        df_existente = pd.read_excel(nombre_archivo)
        # Concatenar los datos actuales con los existentes
        df_combinado = pd.concat([df_existente, df_actualizados], ignore_index=True)
    else:
        # Si el archivo no existe, simplemente usar los datos actuales
        df_combinado = df_actualizados
    
    # Guardar los registros actualizados en el archivo Excel
    df_combinado.to_excel(nombre_archivo, index=False)
    print(f"Cambios exportados exitosamente a {nombre_archivo}")
    
    # Imprimir información sobre los registros actualizados
    print(f"Se han {'simulado' if MODO_PRUEBA else 'realizado'} {len(registros_actualizados)} oportunidades.")
    print("Oportunidades actualizadas:")
    for registro in registros_actualizados:
        print(registro)
        
    # Evitar KeyError si no hubo registros
    if df_actualizados.empty:
        print("No hubo registros que actualizar o que cumplieran el filtro.")
        return []

    #return df_actualizados
    return df_actualizados['id_crm'].tolist()


def main():
    # Obtenemos una conexión a la base de datos
    conn = crear_conexion_sql('BD_PMO')
    cursor = conn.cursor()

    try:
        # Definimos las opciones a ejecutar
        opciones = [1, 2]

        todos_los_id_crm = []

        for opcion in opciones:
            df_opportunity = obtener_datos(cursor, opcion)
            id_crm_actualizados = actualizar_datos_crm(cursor, df_opportunity, opcion)
            todos_los_id_crm.extend(id_crm_actualizados)
            # Solo hacemos commit si NO es modo prueba
            if not MODO_PRUEBA:
                conn.commit()
        
        if MODO_PRUEBA:
            print("[INFO] MODO_PRUEBA ACTIVADO: no se aplicaron cambios en SQL (sin UPDATE ni INSERT, sin COMMIT).")
            # Por si acaso, rollback de cualquier cosa pendiente
            try:
                conn.rollback()
            except Exception:
                pass
        
        # Crear archivo final combinado en la carpeta output/
        os.makedirs(_OUTPUT_DIR, exist_ok=True)
        ruta_archivo_final = os.path.join(_OUTPUT_DIR, "update_dat_Oportunidades.xlsx")

        # Eliminar el archivo si ya existe
        if os.path.exists(ruta_archivo_final):
            os.remove(ruta_archivo_final)

        datos_completos = []
        for id_crm in set(todos_los_id_crm):  # Usamos set para evitar duplicados
            cursor.execute("""
                SELECT id_crm, orden_interna, codigo_servicio, id_datOperaciones
                FROM Datos_CRM
                WHERE id_crm = ?
            """, (id_crm,))
            row = cursor.fetchone()
            if row:
                datos_completos.append({
                    "id_crm": row[0],
                    "orden_interna": row[1],
                    "codigo_servicio": row[2],
                    "id_datOperaciones": row[3]
                })

        df_final = pd.DataFrame(datos_completos)
        df_final.to_excel(ruta_archivo_final, index=False)
        print(f"\nArchivo final generado exitosamente en: {ruta_archivo_final}")
    except Exception as e:
        print("[ERROR] Ocurrió un error, haciendo ROLLBACK...")
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[ERROR] Detalle: {e}")
    finally:
        # Cerrar la conexión
        cursor.close()
        conn.close()
    
    try:
        # Intentamos ejecutar una consulta después de cerrar la conexión.
        cursor.execute("SELECT 1")
    except pyodbc.ProgrammingError as e:
        print(f"La conexión se cerró correctamente: {e}")
    else:
        print("La conexión aún está abierta.")

if __name__ == "__main__":
    main()
