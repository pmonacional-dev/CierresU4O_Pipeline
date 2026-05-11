import pyodbc
from datetime import datetime
import logging
import Conexiones

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def execute_stored_procedure(connection, cursor, procedure_name):
    try:
        logging.info(f"Executing stored procedure: {procedure_name}")
        cursor.execute(f"SET NOCOUNT ON; EXEC [dbo].[{procedure_name}]")
        logging.info(f"Stored procedure {procedure_name} executed.")
        connection.commit()
        logging.info("Transaction committed.")
    except pyodbc.Error as e:
        logging.error(f"Database error occurred: {e}")
        connection.rollback()  # Rollback the transaction in case of an error
    except Exception as e:
        logging.error(f"Error executing stored procedure {procedure_name}: {e}")
        connection.rollback()  # Rollback the transaction in case of an error

def delete_records(cursor, table_name):
    try:
        delete_query = f"DELETE FROM {table_name}"
        cursor.execute(delete_query)
        cursor.commit()
        logging.info(f"Data from {table_name} deleted successfully.")
    except Exception as delete_error:
        logging.error(f"Error in record deletion: {delete_error}")


def transfer_data(central_cursor, remote_cursor, table_name_origen, table_name_destino):
    try:
        chunk_size = 5000
        # Leer datos de tabla en la fuente de datos origen
        central_cursor.execute(f"SELECT * FROM {table_name_origen}")
        columns = [column[0] for column in central_cursor.description]

        insert_query = f"INSERT INTO {table_name_destino} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

        while True:
            batch = central_cursor.fetchmany(chunk_size)
            if not batch:
                break
            remote_cursor.executemany(insert_query, batch)
            remote_cursor.commit()
            logging.info(f"Table: {table_name_origen}: Batch of {len(batch)} rows inserted successfully.")
    except Exception as transfer_error:
        logging.error(f"Error in data transfer: {transfer_error}")

def ProcesoCentralizado(sp_to_process):
    central_conn = None
    central_cursor = None
    remote_conn = None
    remote_cursor = None
    try:
        for sp_name in sp_to_process:
            if sp_name == "spBI_SalesforceNacional_CierreDiario_U4O_17":
                central_conn, central_cursor = Conexiones.connect_SINDATA_saas_sql()
                remote_conn, remote_cursor = Conexiones.connect_QLIK_saas_sql()

                # Eliminar registros en las tablas de la fuente de datos de Dashboards | Edata_Qlik
                tables_to_process = [
                    "SINDATA_GrupoComercial",
                    "SINDATA_GrupoComercial_TeamLeader",
                    "SINDATA_GrupoComercial_TeamMember"
                ]
                for table_name in tables_to_process:
                    delete_records(remote_cursor, table_name)

                # Integrar los datos actualizados en servidor central del cierre diario | SIN_Data
                execute_stored_procedure(central_conn, central_cursor, sp_name)

                # Enviar los datos actualizados a las tablas de la fuente de datos de Dashboards | Edata_Qlik
                transfer_data(central_cursor, remote_cursor,
                              "Salesforce_GrupoComercial",
                              "SINDATA_GrupoComercial")
                transfer_data(central_cursor, remote_cursor,
                              "Salesforce_GrupoComercial_TeamLeader",
                              "SINDATA_GrupoComercial_TeamLeader")
                transfer_data(central_cursor, remote_cursor,
                              "Salesforce_GrupoComercial_TeamMember",
                              "SINDATA_GrupoComercial_TeamMember")

    except pyodbc.Error as e:
        logging.error(f"SQL Server Error: {e}")
    except Exception as main_error:
        logging.error(f"Error in main function: {main_error}")
    finally:
        if central_cursor:
            central_cursor.close()
        if central_conn:
            central_conn.close()
        if remote_cursor:
            remote_cursor.close()
        if remote_conn:
            remote_conn.close()

def ProcesaPeriodo(periodo):
    sp_to_process = ""
    try:
        if periodo == "Diario":
            sp_to_process = ["spBI_SalesforceNacional_CierreDiario_U4O_17"]
        elif periodo == "Semanal":
            sp_to_process = ["spBI_SalesforceNacional_CierreDiario_U4O_17"]

        logging.info(f"Inicinado proceso: {periodo}.")
        return sp_to_process
    except Exception as e:
        logging.error(f"Error in ProcesaPeriodo: {e}")

def main(periodo):
    startTime = datetime.now()
    logging.info('U4O_Integrar_AvanceSeniority | Inicia ejecución ')

    sp_to_process = ProcesaPeriodo(periodo)
    ProcesoCentralizado(sp_to_process)

    logging.info(f'U4O_Integrar_AvanceSeniority | Tiempo de ejecución: {datetime.now() - startTime}')

if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments