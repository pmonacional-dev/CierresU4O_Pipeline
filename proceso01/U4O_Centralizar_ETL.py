from datetime import datetime
import Conexiones
import logging
import pyodbc

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# Main function
def main(origen):
    origen = "Erik"
    startTime = datetime.now()

    try:
        local_sql_cursor = None
        local_connSqlServer = None
        central_sql_cursor = None
        central_connSqlServer = None

        # Envios a datamart QLIK
        local_connSqlServer, local_sql_cursor = Conexiones.connect_ETL_local_sql(origen)
        central_connSqlServer, central_sql_cursor = Conexiones.connect_QLIK_saas_sql()

        # List of tables to process
        #tables_to_process = ["Extraer_Posgrados_U4O"]
        tables_to_process = ["Extraer_Actividades3M", "Reporte_AnalisisAtencionU4O", "Reporte_FiscalHistorico", "Reporte_RelacionEMIS"]

        try:
            for table_name in tables_to_process:
                modified_table_name = "ETL_" + table_name
                delete_query = f"DELETE FROM {modified_table_name}"
                central_sql_cursor.execute(delete_query)
                print(f"Data from selected {modified_table_name} deleted successfully.")

            central_connSqlServer.commit()

        except Exception as delete_error:
            print(f"Error in record deletion: {delete_error}")

        chunk_size = 5000
        try:
            for table_name in tables_to_process:
                local_sql_cursor.execute(f"SELECT * FROM {table_name}")

                # Desactivar fast_executemany para tablas con NVARCHAR(MAX) que truncan el buffer
                central_sql_cursor.fast_executemany = table_name != "Reporte_FiscalHistorico"

                # Fetch data in chunks
                while True:
                    batch = local_sql_cursor.fetchmany(chunk_size)
                    if not batch:
                        break

                    columns = [f"[{column[0]}]" for column in local_sql_cursor.description]
                    modified_table_name = "ETL_" + table_name
                    insert_query = f"INSERT INTO {modified_table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

                    # Insert data in batches
                    central_sql_cursor.executemany(insert_query, batch)
                    central_connSqlServer.commit()

                    print(
                        f"Datamart SINDATA | {modified_table_name} : Batch of {len(batch)} rows from {table_name} inserted successfully.")

        except pyodbc.Error as e:
            print(f"SQL Server Error: {e}")
        finally:
            if local_sql_cursor:
                local_sql_cursor.close()
                local_connSqlServer.close()

            if central_sql_cursor:
                central_sql_cursor.close()
                central_connSqlServer.close()

    except Exception as main_error:
        print(f"Error in main function: {main_error}")

    print('Centralizar_ETL | Tiempo de ejecución :', datetime.now() - startTime)


if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments