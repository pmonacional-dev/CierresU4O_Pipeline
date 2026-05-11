import pyodbc
from datetime import datetime
import logging
import Conexiones

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def delete_records(cursor, table_name):
    try:
        # Modificar para definir la tabla a donde se eliminaran los datos
        if table_name == "Talento_PASE_CRM_Vista":
            table_name = "PASE_CRM_Vista"
        elif table_name == "Talento_NPS_Coordinador_Resumen":
            table_name = "PASE_ActividadExpertos_NPS_Coordinador_Resumen"

        delete_query = f"DELETE FROM {table_name}"
        cursor.execute(delete_query)
        cursor.commit()
        logging.info(f"Data from {table_name} deleted successfully.")
    except Exception as delete_error:
        logging.error(f"Error in record deletion: {delete_error}")


def transfer_data(local_conn, local_cursor, central_cursor, table_name):
    try:
        chunk_size = 2500

        # Leer datos de tabla en la fuente de datos origen
        local_cursor.execute(f"SELECT * FROM {table_name}")
        columns = [column[0] for column in local_cursor.description]
        data = local_cursor.fetchall()  # Fetch all data at once

        # Close local connection after fetching data
        local_cursor.close()
        local_conn.close()

        # Modificar para definir la tabla a donde se enviaran los datos
        if table_name == "Talento_PASE_CRM_Vista":
            table_name = "PASE_CRM_Vista"
        elif table_name == "Talento_NPS_Coordinador_Resumen":
            table_name = "PASE_ActividadExpertos_NPS_Coordinador_Resumen"

        insert_query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

        # Insert rows in chunks
        for i in range(0, len(data), chunk_size):
            batch = data[i:i + chunk_size]
            central_cursor.executemany(insert_query, batch)
            central_cursor.commit()
            logging.info(f"Table: {table_name}: Batch of {len(batch)} rows inserted successfully.")
    except Exception as transfer_error:
        logging.error(f"Error in data transfer: {transfer_error}")


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


def ProcesoCentralizado(periodo, tables_to_process):
    try:
        for table_name in tables_to_process:
            if table_name == "EmpresaCRM_Qualtrics":
                local_conn, local_cursor = Conexiones.connect_PASE_saas_sql()
                central_conn, central_cursor = Conexiones.connect_SINDATA_saas_sql()
            elif table_name == "EmpresaCRM":
                local_conn, local_cursor = Conexiones.connect_SINDATA_saas_sql()
                central_conn, central_cursor = Conexiones.connect_PASE_saas_sql()
                delete_records(central_cursor, "Qualtrics_RelacionEmpresas")
            else:
                local_conn, local_cursor = Conexiones.connect_PASE_saas_sql()
                central_conn, central_cursor = Conexiones.connect_QLIK_saas_sql()

            delete_records(central_cursor, table_name)
            transfer_data(local_conn, local_cursor, central_cursor, table_name)
            ProcedimientosAlmacenados(periodo, table_name)

    except pyodbc.Error as e:
        logging.error(f"SQL Server Error: {e}")
    except Exception as main_error:
        logging.error(f"Error in main function: {main_error}")
    finally:
        if central_cursor:
            central_cursor.close()
            central_conn.close()


def ProcedimientosAlmacenados(periodo, table_name):
    try:
        sp_conn, sp_cursor = Conexiones.connect_PASE_saas_sql()
        if table_name == "EmpresaCRM":
            execute_stored_procedure(sp_conn, sp_cursor, "WS_Talento_Qualtrics_RelacionEmpresas")
        elif table_name == "Talento_PASE_CRM_Vista":
            execute_stored_procedure(sp_conn, sp_cursor, "WS_Talento_AltaExpertos_REVEC_GeneraReporteMatriz")

    except pyodbc.Error as e:
        logging.error(f"SQL Server Error: {e}")
    except Exception as main_error:
        logging.error(f"Error in main function: {main_error}")
    finally:
        if sp_cursor:
            sp_cursor.close()
            sp_conn.close()


def ProcesaPeriodo(periodo):
    tables_to_process = ""
    try:
        if periodo == "Diario":
            tables_to_process = ["Talento_PASE_CRM_Vista"]
        elif periodo == "Semanal":
            tables_to_process = ["Talento_PASE_CRM_Vista", "PASE_Usuarios", "PASE_Consultas", "PASE_AccesosInternos"]
        elif periodo == "Mensual1":
            tables_to_process = ["EmpresaCRM_Qualtrics"]
        elif periodo == "Mensual2":
            tables_to_process = [
                "EmpresaCRM",
                "PASE_ActividadExpertos_Actividad",
                "PASE_ActividadExpertos_Capacitaciones",
                "PASE_ActividadExpertos_Empresas",
                "PASE_ActividadExpertos_ExpertiseArea",
                "PASE_ActividadExpertos_ExpertiseSubArea",
                "PASE_ActividadExpertos_Idiomas",
                "PASE_ActividadExpertos_Reseñas",
                "PASE_ActividadExpertos_Residencia",
                "Talento_NPS_Coordinador_Resumen",
                "PASE_ActividadExpertos_NPS_Coordinador"
            ]

        logging.info(f"Inicinado proceso: {periodo}.")
        return tables_to_process
    except Exception as e:
        logging.error(f"Error in ProcesaPeriodo: {e}")


def main(periodo):
    startTime = datetime.now()
    logging.info('U4O_Centralizar_PASE | Inicia ejecución ')

    tables_to_process = ProcesaPeriodo(periodo)
    ProcesoCentralizado(periodo, tables_to_process)

    logging.info(f'U4O_Centralizar_PASE | Tiempo de ejecución: {datetime.now() - startTime}')


if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments