import mysql.connector
import pyodbc
from datetime import datetime
import Conexiones

# Main function
def main(origen):
    startTime = datetime.now()

    # Initialize variables
    mysql_connection = None
    mysql_cursor = None
    conn_sql_server = None
    sql_cursor = None
    chunk_size = 1000
    offset = 0
    contadoreliminar = 0

    # Establish the connection
    try:
        mysql_connection, mysql_cursor, mysql_table = Conexiones.connect_TLGU4P_mysql()
        conn_sql_server, sql_cursor = Conexiones.connect_ETL_local_sql(origen)

        """ columnas existentes antes de modificación del equipo u4P"""
        """"""
        # Specify the columns in the SELECT statement
        select_columns = """
             `real/plan`, `semestre`, `folio`, `región`,
             `campus`, `nombre_del_programa`, `fecha_de_inicio`, `fecha_y_hora_de_venta`,
             `propietario`, `participantes_inscritos`, `apertura:_ingreso_real_(sin_iva)`, `estatus_confirmado`,
             `meta_campus`, `modalidad`, `correo_propietario`, `equipo_de_atención`,
             `fuente`, `fecha_arranque`, `fecha_fin`, `area_tematica`,
             `escuela_nacional`, `tipo_programa`
        """
        """"""

        select_columns = """
             `real/plan`, `semestre`, `folio`, `region`,
             `campus`, `nombre_programa`, `fecha_venta`, `fecha_hora_venta`,
             `propietario`, `participantes_inscritos`, `ingreso`, `estatus_confirmado`,
             `meta_campus`, `modalidad`, `correo_propietario`, `equipo_atencion`,
             `fuente`, `fecha_arranque`, `fecha_fin`, `area_tematica`,
             `escuela_nacional`, `tipo_programa`
        """

        while True:
            # Execute a query to select rows in chunks
            query = f"SELECT {select_columns} FROM {mysql_table} LIMIT {chunk_size} OFFSET {offset}"
            mysql_cursor.execute(query)
            mysql_rows = mysql_cursor.fetchall()

            # Check if there are records
            if len(mysql_rows) > 0 and contadoreliminar == 0:
                print("Eliminar el historial de leads de inscritos TLG desde U4P")
                try:
                    # Delete history of TLG components
                    sql_cursor.execute("DELETE FROM Extraer_TLG_U4P")
                    # Commit the changes
                    conn_sql_server.commit()
                    print("Registros TLG desde U4P eliminados")
                    contadoreliminar = 1
                except Exception as delete_error:
                    print(f"Error en eliminación de registros: {delete_error}")


            if not mysql_rows:
                print("No more rows to fetch.")
                break  # No more rows to fetch, break out of the loop

            # Process the fetched rows (e.g., insert into SQL Server)
            for mysql_row in mysql_rows:


                # Define the SQL query for insertion into SQL Server
                insert_query = """
                INSERT INTO Extraer_TLG_U4P (
                    real_plan, semestre, folio, region,
                    campus, nombre_programa, fecha_inicio, fecha_hora_venta,
                    propietario, participantes_inscritos, ingreso_real_siniva, estatus_confirmado,
                    meta_campus, modalidad, correo_propietario, equipo_atencion,
                    fuente, fecha_arranque, fecha_fin, area_tematica,
                    escuela_nacional, tipo_programa
                ) VALUES (
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,
                    ?,?
                )
                """

                # Verify that there is data to insert
                if mysql_row:
                    # Insert each row from MySQL into SQL Server
                    sql_cursor.execute(insert_query, *mysql_row)

            offset += chunk_size

            # Commit the changes
            conn_sql_server.commit()
            print("Data inserted successfully.")
            print(len(mysql_rows), " registros")

    except mysql.connector.Error as e:
        print(f"MySQL Error: {e}")

    except pyodbc.Error as e:
        print(f"SQL Server Error: {e}")

    finally:
        # Close the cursor and connection for both MySQL and SQL Server
        if mysql_cursor:
            mysql_cursor.close()
            mysql_connection.close()

        if sql_cursor:
            sql_cursor.close()
            conn_sql_server.close()  # Close the SQL Server connection

    print('U4O_Extraer_TLG_U4P | Tiempo de ejecución :', datetime.now() - startTime)
    
if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments