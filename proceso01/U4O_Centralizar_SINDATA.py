import pyodbc
from datetime import datetime
import Conexiones
import logging
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def delete_records(cursor, table_name):
    try:
        # Modify table name if needed
        table_name = modify_table_name(table_name)
        delete_query = f"DELETE FROM {table_name}"
        cursor.execute(delete_query)
        cursor.commit()
        logging.info(f"Table: {table_name} | Deleted successfully.")
    except Exception as delete_error:
        logging.error(f"Error in record deletion: {delete_error}")


def modify_table_name(table_name):
    if "Salesforce_" in table_name:
        table_name = table_name.replace("Salesforce_", "SINDATA_")
    return table_name


def convert_to_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value


def transfer_data(local_conn, local_cursor, central_cursor, table_name):
    try:
        chunk_size = 2500
        if table_name == 'Salesforce_IndicadorIndustria':
            local_cursor.execute(
                f"SELECT DISTINCT * FROM {table_name} WHERE IndicadorIndustria_FechaCierreAnalytics = (SELECT MAX(IndicadorIndustria_FechaCierreAnalytics) FROM {table_name})")
        elif table_name == 'Salesforce_MovimientoDiarios':
            local_cursor.execute(
                f"SELECT * FROM {table_name} WHERE CONVERT(datetime, MovimientoDiarios_FechaMovimiento, 103) = (SELECT MAX(CONVERT(datetime, MovimientoDiarios_FechaMovimiento, 103)) FROM {table_name})")
        else:
            local_cursor.execute(f"SELECT * FROM {table_name}")

        columns = [column[0] for column in local_cursor.description]
        data = local_cursor.fetchall()  # Fetch all data at once

        # Close local connection after fetching data
        local_cursor.close()
        local_conn.close()

        # Modify table name if needed
        table_name = modify_table_name(table_name)
        insert_query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

        while True:
            batch = data[:chunk_size]
            data = data[chunk_size:]
            if not batch:
                break
            central_cursor.executemany(insert_query, batch)
            central_cursor.commit()
            logging.info(f"Table: {table_name} | Batch of {len(batch)} rows inserted successfully.")
    except Exception as transfer_error:
        logging.error(f"Error in data transfer: {transfer_error}")


def transfer_data_columns(local_conn, local_cursor, central_cursor, table_name, columns_to_select):
    try:
        # Initialize a variable to keep track of the total number of chunks inserted
        total_chunks_inserted = 0
        total_rows_inserted = 0
        chunk_size = 2500
        if table_name == 'Salesforce_IndicadorNacional':
            local_cursor.execute(
                f"SELECT {', '.join(columns_to_select)} FROM {table_name} WHERE FechaCierreAnalytics = (SELECT MAX(FechaCierreAnalytics) FROM {table_name})")
        else:
            local_cursor.execute(f"SELECT {', '.join(columns_to_select)} FROM {table_name}")

        columns = [column[0] for column in local_cursor.description]
        df = pd.DataFrame.from_records(local_cursor.fetchall(), columns=columns)

        # Close local connection after fetching data
        local_cursor.close()
        local_conn.close()

        # Replace None with NaN, then replace NaN with None for SQL NULL compatibility
        df.replace({None: None, np.nan: None}, inplace=True)

        # Modify table name if needed
        table_name = modify_table_name(table_name)
        insert_query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})"

        # Insert rows in chunks
        for i in range(0, len(df), chunk_size):
            chunk = df.iloc[i:i + chunk_size]
            data = [tuple(row) for row in chunk.values]
            central_cursor.executemany(insert_query, data)
            central_cursor.connection.commit()
            total_chunks_inserted += 1
            total_rows_inserted += len(chunk)
            logging.info(f"Table: {table_name} | Batch of {len(chunk)} rows inserted successfully.")
        logging.info(f"Table: {table_name} | Total rows inserted: {total_rows_inserted}")
    except Exception as transfer_error:
        logging.error(f"Error in data transfer: {transfer_error}")
        raise  # Re-raise the exception after logging it


def execute_stored_procedure(connection, cursor, procedure_name):
    try:
        cursor.execute(f"SET NOCOUNT ON; EXEC [dbo].[{procedure_name}]")
        connection.commit()
        logging.info(f"Stored procedure {procedure_name} executed successfully.")
        cursor.close()
        connection.close()
    except Exception as e:
        logging.error(f"Error executing stored procedure {procedure_name}: {e}")


def ProcesoCentralizado(periodo, tables_to_process):
    try:
        for table_name in tables_to_process:
            local_conn, local_cursor = Conexiones.connect_SINDATA_saas_sql()
            central_conn, central_cursor = Conexiones.connect_QLIK_saas_sql()

            delete_records(central_cursor, table_name)

            if table_name == 'Salesforce_AlteryxData_Historico_U4O':
                columns_to_select = [
                    'IdEmpresa',
                    'IdOportunidad',
                    'IdContacto',
                    'NombreEmpresa',
                    'AreaTematica',
                    'Coordinador',
                    'Coordinador_IdPASE',
                    'Diseñador',
                    'Diseñador_IdPASE',
                    'Escuela',
                    'FechaAnalytics',
                    'InicioEjecucion',
                    'TerminoEjecucion',
                    'Impacto_CapacidadAccion',
                    'Industria',
                    'IndustriaU4O',
                    'MotivoPerdida',
                    'Sector',
                    'SubSector',
                    'TipoPrograma',
                    'TipoIniciativa',
                    'TipoRegistro',
                    'FechaCreacion',
                    'Etapa',
                    'Importe',
                    'Participantes',
                    'Origen',
                    'Referido',
                    'Modalidad1',
                    'Modalidad2',
                    'Modalidad3',
                    'Modalidad4',
                    'Modalidad5',
                ]
                transfer_data_columns(local_conn, local_cursor, central_cursor, table_name, columns_to_select)
            elif table_name == 'Salesforce_IndicadorNacional':
                columns_to_select = [
                    'ImporteDivisa',
                    'ImporteDivisaAjuste',
                    'Importe',
                    'CampusUsuario',
                    'NombreOportunidad',
                    'FechaCierreOportunidad',
                    'Probabilidad',
                    'Antiguedad',
                    'FechaCreación',
                    'FechaRealCreación',
                    'NombreCuenta',
                    'PropietarioOportunidad',
                    'Etapa',
                    'Ceco',
                    'Participantes',
                    'Coordinador',
                    'Duración',
                    'TipoRegistro',
                    'Zona',
                    'FechaCierreAnalytics',
                    'CalificaCuenta',
                    'AlteryxIdOportunidad',
                    'Clave',
                    'Status'
                ]
                transfer_data_columns(local_conn, local_cursor, central_cursor, table_name, columns_to_select)
            else:
                transfer_data(local_conn,local_cursor, central_cursor, table_name)

    except pyodbc.Error as e:
        logging.error(f"SQL Server Error: {e}")
    except Exception as main_error:
        logging.error(f"Error in main function: {main_error}")
    finally:
        if central_cursor:
            central_cursor.close()
            central_conn.close()


def ProcesaPeriodo(periodo):
    try:
        tables_to_process = [

            # Envio de tablas desde SIN_DATA
            'Salesforce_MovimientoDiarios',
            'Salesforce_StatusKAM',
            'Salesforce_AvanceMetaActiva',
            'Salesforce_AvanceMetaActiva_Asesor',
            'Salesforce_AvanceMetaActiva_EficienciaAsesor_Tableau',
            'Salesforce_ComparaMetaAnual',
            'Salesforce_DiseñoRutaMeta',
            'Salesforce_RutaActividad_Asesor',
            'Salesforce_MovimientoEtapas',
            'Salesforce_AlteryxData_Historico_U4O',
            'Salesforce_IndicadorNacional',
            'Salesforce_IndicadorIndustria',

            # Envio de vistas desde SIN DATA
            'SINDATA_ConsultoriaEmpresas',
            'SINDATA_NombreCorrecto_EmpresaCRM'

        ]

        if periodo == "Semanal":
            # New list of values to add if periodo is "Semanal"
            new_list = [
                "SINDATA_Empresa_Industria_Sector"
            ]
            tables_to_process.extend(new_list)

        ProcesoCentralizado(periodo, tables_to_process)

    except Exception as e:
        logging.error(f"Error in ProcesaPeriodo: {e}")


def main(periodo):
    startTime = datetime.now()
    logging.info('U4O_Centralizar_SINDATA  | Inicia ejecución ')
    ProcesaPeriodo(periodo)
    logging.info(f'U4O_Centralizar_SINDATA | Tiempo de ejecución: {datetime.now() - startTime}')


if __name__ == "__main__":
    main(None)
    #main('diario')