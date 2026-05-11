from datetime import datetime
import logging
import pyodbc
import Conexiones

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def ProcesoCentralizado(seleccion, local_sql_cursor, central_sql_cursor, central_connSqlServer):
    if seleccion == "Historico":
        try:
            # List of tables to process
            tables_to_process = ["Inteligencia_Vista_Historico"]
            columns_to_process = [
                "CECO", "FechaAnalytics", "FechaCreación", "FechaCierre", "CampusUsuario",
                "IdPropietario", "PropietarioOportunidad", "EmpresaHomologado", "EmpresaCRM",
                "NombreOportunidad", "Objetivo", "Descripcion", "Importe", "Zona", "EtapaDetalle",
                "Antiguedad", "AñoAlta", "AñoMeta", "Participantes", "TipoRegistro", "Industria",
                "Sector", "SubSector", "IndustriaEstratégica", "TipoPrograma", "Escuela", "Duración",
                "IdOportunidad", "Coordinador", "Diseñador", "AreaTematica", "MotivoPerdida",
                "TipoIniciativa", "Origen", "Referido", "InicioEjecucion", "TerminoEjecucion"
            ]

            columns_str = ", ".join(columns_to_process)  # Join columns with commas

            try:
                for table_name in tables_to_process:
                    modified_table_name = "SINDATA_" + table_name
                    delete_query = f"DELETE FROM {modified_table_name}"
                    central_sql_cursor.execute(delete_query)
                    logging.info(f"Data from selected {modified_table_name} deleted successfully.")

                central_connSqlServer.commit()

            except Exception as delete_error:
                logging.error(f"Error in record deletion: {delete_error}")

            chunk_size = 2500
            try:
                for table_name in tables_to_process:
                    local_sql_cursor.execute(f"SELECT {columns_str} FROM {table_name}")

                    # Fetch data in chunks
                    while True:
                        batch = local_sql_cursor.fetchmany(chunk_size)
                        if not batch:
                            break

                        columns = [column[0] for column in local_sql_cursor.description]
                        modified_table_name = "SINDATA_" + table_name
                        insert_query = f"INSERT INTO {modified_table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

                        # Insert data in batches
                        central_sql_cursor.executemany(insert_query, batch)
                        central_connSqlServer.commit()

                        logging.info(
                            f"Datamart INTELIGENCIAVEC Azure | {modified_table_name} : Batch of {len(batch)} rows "
                            f"inserted successfully.")

            except pyodbc.Error as e:
                logging.error(f"SQL Server Error: {e}")

        except Exception as main_error:
            logging.error(f"Error in main function: {main_error}")

    elif seleccion == "NuevasOportunidades":
        try:
            tables_to_process = ["SINDATA_MovimientoDiarios_NuevaOp"]

            try:
                for table_name in tables_to_process:
                    delete_query = f"DELETE FROM {table_name}"
                    central_sql_cursor.execute(delete_query)
                    logging.info(f"Data from selected {table_name } deleted successfully.")

                central_connSqlServer.commit()

            except Exception as delete_error:
                logging.error(f"Error in record deletion: {delete_error}")

            chunk_size = 2500
            for table_name in tables_to_process:
                try:
                    local_sql_cursor.execute(
                        """
                        SELECT t1.MovimientoDiarios_AlteryxIdOportunidad as 'ID_OPORTUNIDAD',
                        t3.IdPropietario AS 'ID_ASESOR',
                        t3.IdEmpresa as 'ID_Empresa',
                        CASE 
                            WHEN [IndicadorIndustria_Campus] = 'Campus Santa Fe' THEN 'MÉXICO CIUDAD DE MÉXICO' 
                            WHEN [IndicadorIndustria_Campus] = 'Campus Ciudad de México' THEN 'MÉXICO CIUDAD DE MÉXICO' 
                            WHEN [IndicadorIndustria_Campus] LIKE '%Campus%' THEN UPPER(CONCAT('MÉXICO ', REPLACE([IndicadorIndustria_Campus], 'Campus ', ''))) 
                            WHEN [IndicadorIndustria_Campus] LIKE '%LATAM%' THEN UPPER(REPLACE([IndicadorIndustria_Campus], 'LATAM - ', ''))
                        END as 'ZONA',
                        UPPER(t1.MovimientoDiarios_NombreOportunidad) as 'OPORTUNIDAD',
                        UPPER(t2.IndicadorIndustria_Empresa) AS 'EMPRESA',
                        UPPER(CONCAT(t2.[IndicadorIndustria_Sector], ': ', t2.IndicadorIndustria_SubSector)) as 'SECTOR'
                        FROM [dbo].[Salesforce_MovimientoDiarios] t1
                        INNER JOIN (SELECT [AlteryxIdOportunidad], [IndicadorIndustria_Campus], [IndicadorIndustria_Empresa], [IndicadorIndustria_Sector], [IndicadorIndustria_SubSector]
                            FROM [dbo].[Salesforce_IndicadorIndustria] 
                            WHERE [IndicadorIndustria_FechaCierreAnalytics] = (SELECT MAX([IndicadorIndustria_FechaCierreAnalytics]) FROM [dbo].[Salesforce_IndicadorIndustria])
                            ) t2 ON t1.MovimientoDiarios_AlteryxIdOportunidad = t2.AlteryxIdOportunidad
                        INNER JOIN [dbo].[Salesforce_AlteryxData_Historico_U4O] t3 ON t1.MovimientoDiarios_AlteryxIdOportunidad = t3.IdOportunidad
                        WHERE CONVERT(DATE,MovimientoDiarios_FechaMovimiento,103) = (SELECT MAX(CONVERT(DATE,MovimientoDiarios_FechaMovimiento,103)) FROM [SIN_Data].[dbo].[Salesforce_MovimientoDiarios])
                        AND [MovimientoDiarios_EtapaDetalle] = 'Oportunidad'
                        """
                    )

                    columns = [column[0] for column in local_sql_cursor.description]
                    data = local_sql_cursor.fetchall()  # Fetch all data at once
                    insert_query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

                    while True:
                        batch = data[:chunk_size]
                        data = data[chunk_size:]
                        if not batch:
                            break
                        central_sql_cursor.executemany(insert_query, batch)
                        central_connSqlServer.commit()
                        logging.info(f"Table: {table_name} | Batch of {len(batch)} rows inserted successfully.")
                except Exception as transfer_error:
                    logging.error(f"Error in data transfer: {transfer_error}")

        except Exception as main_error:
            logging.error(f"Error in main function: {main_error}")

def main(origen, recurrencia):
    startTime = datetime.now()
    logging.info('U4O_Centralizar_Inteligencia | Inicia ejecución ')

    local_sql_cursor = None
    local_connSqlServer = None
    central_sql_cursor = None
    central_connSqlServer = None

    try:
        # Envios a datamart de procesos de extracción para indicadores U4O
        local_connSqlServer, local_sql_cursor = Conexiones.connect_SINDATA_local_sql(origen)
        central_connSqlServer, central_sql_cursor = Conexiones.connect_INTELIGENCIA_saas_sql()

        # Diaria
        if recurrencia == "Diario":
            # ETL Depreciada por migración y ahorro de costos en la nube institucional. ETL Se mantendrá de forma local
            ProcesoCentralizado("NuevasOportunidades", local_sql_cursor, central_sql_cursor, central_connSqlServer)
        # Semanal
        elif recurrencia == "Semanal":
            ProcesoCentralizado("NuevasOportunidades", local_sql_cursor, central_sql_cursor, central_connSqlServer)
            ProcesoCentralizado("Historico", local_sql_cursor, central_sql_cursor, central_connSqlServer)

    except Exception as e:
        logging.error(f"Error in main function: {e}")

    finally:
        if local_sql_cursor:
            local_sql_cursor.close()
        if local_connSqlServer:
            local_connSqlServer.close()
        if central_sql_cursor:
            central_sql_cursor.close()
        if central_connSqlServer:
            central_connSqlServer.close()

    logging.info(f'U4O_Centralizar_Inteligencia | Tiempo de ejecución: {datetime.now() - startTime}')

if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments