# -*- coding: utf-8 -*-
"""
Script para extraer registros recientes desde la tabla Portafolio_PMO
y registrar aquellos que no han sido previamente enviados a la tabla 
Envios_cerradas_ganadas. Además, permite notificar vía Teams.

Autor: Antonio Guerrero
Fecha de creación: 29-May-2023
"""

import pyodbc
import pandas as pd
from datetime import datetime, timedelta
from Conexion_SQL import crear_conexion_sql
from Teams_Messages import TeamsWebhook

def obtener_datos(cursor, today):
    """
    Extrae registros de la tabla Portafolio_PMO cuya fecha de cierre 
    es mayor o igual al día especificado.

    Parámetros:
        cursor (pyodbc.Cursor): Cursor conectado a la base de datos.
        today (datetime.date): Fecha de corte.

    Retorna:
        pd.DataFrame: Registros obtenidos de la tabla.
    """
    
    # Ejecutamos la consulta.
    cursor.execute(f"""
        SELECT * 
        FROM Portafolio_PMO 
        WHERE fecha_cierre_CRM >= '{today}'
    """)

    # Recogemos los resultados.
    rows = cursor.fetchall()

    # Obtenemos los nombres de las columnas.
    columns = [column[0] for column in cursor.description]

    # Convertimos los resultados en un DataFrame.
    df = pd.DataFrame.from_records(rows, columns=columns)

    return df

def insertar_datos(df, cursor):
    """
    Inserta en la tabla Envios_cerradas_ganadas los registros que aún no existen.

    Parámetros:
        df (pd.DataFrame): Registros extraídos desde Portafolio_PMO.
        cursor (pyodbc.Cursor): Cursor conectado a la base de datos.

    Retorna:
        int: Número de registros insertados.
    """
    
    reg_insertados = 0
    
    # Asegúrate de que las columnas 'id_oportunidad_CRM' y 'fecha_cierre_CRM' existen en tu DataFrame.
    if 'id_oportunidad_CRM' in df.columns and 'fecha_cierre_CRM' in df.columns:
        for index, row in df.iterrows():
            try:
                cursor.execute("""
                    SELECT * 
                    FROM Envios_cerradas_ganadas 
                    WHERE id_crm = ? 
                    AND fecha_cerrada_ganada = ?
                """, row['id_oportunidad_CRM'], row['fecha_cierre_CRM'])

                # Si no hay ninguna fila que coincida, entonces insertamos la nueva fila.
                if cursor.fetchone() is None:
                    cursor.execute("""
                        INSERT INTO Envios_cerradas_ganadas (
                            id_crm, 
                            fecha_cerrada_ganada, 
                            estatus_envio
                            )
                        VALUES (?, ?, ?)
                    """, row['id_oportunidad_CRM'], row['fecha_cierre_CRM'], 0)
                    
                    print("Registro insertado exitosamente:", row['id_oportunidad_CRM'], row['fecha_cierre_CRM'])
                    reg_insertados += 1
                else:
                   print("El registro ya existe, no se hace nada:", row['id_oportunidad_CRM'], row['fecha_cierre_CRM'])

            except pyodbc.Error as e:
                print(f"Error al insertar fila: {e}")
        print('Se han insertado ' + str(reg_insertados) + ' registros en la tabla Datos_CRM\n')

    else:
        print("Las columnas 'id_oportunidad_CRM' y/o 'fecha_cierre_CRM' no existen en el DataFrame.")
    
    return reg_insertados
    
def main():
    
    webhook_url = "https://tecmx.webhook.office.com/webhookb2/83f961cc-56b2-4ac1-a1e8-7f94f7f52872@c65a3ea6-0f7c-400b-8934-5a6dc1705645/IncomingWebhook/009e3db489df48c09fb28b9e32ad34d8/05e0279c-e948-4eaa-b067-3d06b02c3ad4"
    teams_webhook = TeamsWebhook(webhook_url)
    
    # Obtenemos un cursor a la base de datos.
    conn = crear_conexion_sql('BD_PMO')
    cursor = conn.cursor()
    
    # Obtenemos la fecha actual.
    today = datetime.today().date()
    
    # Si hoy es lunes (0), resta 3 días a la fecha.
    if today.weekday() == 0:
        today = today - timedelta(days=40)
    # Si hoy es domingo (6), resta 2 día a la fecha.
    #if today.weekday() == 6:
        #today = today - timedelta(days=2) 
        print("Fecha de cierre ajustada al:", today)
    else:
        today = today - timedelta(days=40) 
        print("Hoy no es lunes, la fecha actual es:", today)

    df = obtener_datos(cursor, today)
    #teams_webhook.send_message("Registros obtenidos", "Se han obtenido: " + str(len(df)) + " nuevos registros en la tabla Portafolio_PMO")

    a = insertar_datos(df, cursor)
    
    """"
    if a > 0:
        teams_webhook.send_message("Proceso cerradas ganadas", "Se han insertado " + str(a) + " nuevos registros en la tabla Datos_CRM\n")
    else:
        print('Sin reg nuevos')
    """

    # Commit de los cambios.
    conn.commit()
    
    # Cerrar la conexión
    cursor.close()
    
    try:
        # Intentamos ejecutar una consulta después de cerrar la conexión.
        cursor.execute("SELECT 1")
    except pyodbc.ProgrammingError as e:
        print(f"La conexión se cerró correctamente: {e}")
    else:
        print("La conexión aún está abierta.")

if __name__ == "__main__":
    main()
    
