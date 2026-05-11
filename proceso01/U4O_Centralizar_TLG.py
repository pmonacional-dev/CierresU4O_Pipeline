from datetime import datetime
import logging
import pyodbc
import Conexiones

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def ProcesoCentralizado(seleccion, origen):
    if seleccion == "QLIK":
        try:
            # Envios a datamart Dashboards Qlik 
            local_sql_cursor = None
            local_connSqlServer = None
            central_sql_cursor = None
            central_connSqlServer = None

            # Envios a datamart de procesos de extracción para indicadores U4P
            local_connSqlServer, local_sql_cursor = Conexiones.connect_ETL_local_sql(origen)
            central_connSqlServer, central_sql_cursor = Conexiones.connect_QLIK_saas_sql()

            # List of tables to process
            tables_to_process = ["Extraer_TLG_U4P"]
            columns_to_process = ["folio", "campus", "nombre_programa", "fecha_inicio", "propietario",
                                  "participantes_inscritos", "ingreso_real_siniva", "estatus_confirmado",
                                  "fecha_arranque",
                                  "fecha_fin", "area_tematica", "escuela_nacional", "tipo_programa"]

            # Construct the SELECT statement dynamically
            columns_str = ", ".join(columns_to_process)  # Join columns with commas

            try:
                for table_name in tables_to_process:
                    modified_table_name = "ETL_" + table_name
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
                        modified_table_name = "ETL_" + table_name
                        insert_query = f"INSERT INTO {modified_table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

                        # Insert data in batches
                        central_sql_cursor.executemany(insert_query, batch)
                        central_connSqlServer.commit()

                        logging.info(f"Datamart Qlik Azure | {table_name} : Batch of {len(batch)} rows inserted successfully.")

            except pyodbc.Error as e:
                logging.error(f"SQL Server Error: {e}")
            finally:
                if local_sql_cursor:
                    local_sql_cursor.close()
                    local_connSqlServer.close()

                if central_sql_cursor:
                    central_sql_cursor.close()
                    central_connSqlServer.close()

        except Exception as main_error:
            logging.error(f"Error in main function: {main_error}")

        try:
            # Envios a datamart Dashboards Qlik  
            local_sql_cursor = None
            local_connSqlServer = None

            central_sql_cursor = None
            central_connSqlServer = None

            # Envios a datamart de procesos de extracción para indicadores U4O
            local_connSqlServer, local_sql_cursor = Conexiones.connect_ETL_local_sql(origen)
            central_connSqlServer, central_sql_cursor = Conexiones.connect_QLIK_saas_sql()

            # List of tables to process
            tables_to_process = ["TLG_ListaComponentes", "Extraer_TLG_Porcentaje", "Extraer_TLG_Componente"]
            columns_str = ", ".join(columns_to_process)  # Join columns with commas

            try:
                for table_name in tables_to_process:
                    modified_table_name = "ETL_" + table_name
                    delete_query = f"DELETE FROM {modified_table_name}"
                    central_sql_cursor.execute(delete_query)
                    logging.info(f"Data from selected {modified_table_name} deleted successfully.")

                central_connSqlServer.commit()

            except Exception as delete_error:
                logging.error(f"Error in record deletion: {delete_error}")

            chunk_size = 2500
            try:
                for table_name in tables_to_process:
                    local_sql_cursor.execute(f"SELECT * FROM {table_name}")

                    # Fetch data in chunks
                    while True:
                        batch = local_sql_cursor.fetchmany(chunk_size)
                        if not batch:
                            break

                        columns = [column[0] for column in local_sql_cursor.description]
                        modified_table_name = "ETL_" + table_name
                        insert_query = f"INSERT INTO {modified_table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

                        # Insert data in batches
                        central_sql_cursor.executemany(insert_query, batch)
                        central_connSqlServer.commit()

                        logging.info(
                            f"Datamart Dashboards Qlik| {modified_table_name} : Batch of {len(batch)} rows inserted successfully.")

            except pyodbc.Error as e:
                logging.error(f"SQL Server Error: {e}")
            finally:
                if local_sql_cursor:
                    local_sql_cursor.close()
                    local_connSqlServer.close()

                if central_sql_cursor:
                    central_sql_cursor.close()
                    central_connSqlServer.close()

        except Exception as main_error:
            logging.error(f"Error in main function: {main_error}")


    elif seleccion == "SINDATA":
        try:
            # Envios a datamart SIN_Data
            local_sql_cursor = None
            local_connSqlServer = None

            central_sql_cursor = None
            central_connSqlServer = None

            # Envios a datamart de procesos de extracción para indicadores U4O
            local_connSqlServer, local_sql_cursor = Conexiones.connect_ETL_local_sql(origen)
            central_connSqlServer, central_sql_cursor =  Conexiones.connect_SINDATA_saas_sql()

            # List of tables to process
            tables_to_process = ["Extraer_TLG_Porcentaje", "Extraer_ActividadesU4O", "Extraer_HistoriaOportunidadesU4O"]
            #columns_str = ", ".join(columns_to_process)  # Join columns with commas

            try:
                for table_name in tables_to_process:
                    modified_table_name = "ETL_" + table_name
                    delete_query = f"DELETE FROM {modified_table_name}"
                    central_sql_cursor.execute(delete_query)
                    logging.info(f"Data from selected {modified_table_name} deleted successfully.")

                central_connSqlServer.commit()

            except Exception as delete_error:
                logging.error(f"Error in record deletion: {delete_error}")

            chunk_size = 2500
            try:
                for table_name in tables_to_process:
                    local_sql_cursor.execute(f"SELECT * FROM {table_name}")

                    # Fetch data in chunks
                    while True:
                        batch = local_sql_cursor.fetchmany(chunk_size)
                        if not batch:
                            break

                        columns = [column[0] for column in local_sql_cursor.description]
                        modified_table_name = "ETL_" + table_name
                        insert_query = f"INSERT INTO {modified_table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

                        # Insert data in batches
                        central_sql_cursor.executemany(insert_query, batch)
                        central_connSqlServer.commit()

                        logging.info(
                            f"Datamart SINDATA Azure | {modified_table_name} : Batch of {len(batch)} rows inserted "
                            f"successfully.")

            except pyodbc.Error as e:
                logging.error(f"SQL Server Error: {e}")
            finally:
                if local_sql_cursor:
                    local_sql_cursor.close()
                    local_connSqlServer.close()

                if central_sql_cursor:
                    central_sql_cursor.close()
                    central_connSqlServer.close()

        except Exception as main_error:
            logging.error(f"Error in main function: {main_error}")


def main(origen):
    startTime = datetime.now()
    logging.info('U4O_Centralizar_TLG | Inicia ejecución ')

    ProcesoCentralizado("QLIK", origen)
    ProcesoCentralizado("SINDATA", origen)

    logging.info(f'U4O_Centralizar_TLG | Tiempo de ejecución: {datetime.now() - startTime}')

if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments