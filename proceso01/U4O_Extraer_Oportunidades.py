from datetime import datetime
from simple_salesforce.exceptions import SalesforceMalformedRequest
import Conexiones

def delete_records(cursor):
    try:
        cursor.execute("DELETE FROM Extraer_OportunidadesU4O")
        cursor.execute("DELETE FROM Extraer_AsesoresU4O")
        cursor.commit()
    except Exception as e:
        print("Error deleting records:", e)


def normalize_date(datestring):
    if datestring is not None:
        try:
            if len(str(datestring)) == 13:
                datestring = str(datestring)
                datestring = datestring[:-3]
                datestring = datetime.fromtimestamp(int(datestring))
                datestring = str(datestring)
            else:
                datestring = datetime.strptime(datestring[:-9], '%Y-%m-%dT%H:%M:%S')
                #datestring = datestring.strftime('%Y-%m-%d')
                datestring = str(datestring)
        except (TypeError, NameError): # unicode is a default on python 3
            pass
    return datestring


def extract_opportunities(sf, cursor, fields):
    try:
        query = """
            SELECT {} FROM Opportunity
            WHERE StageName IN ('Cerrada Ganada','Cerrada Perdida', 'Oportunidad', 'Propuesta', 'Negociación') 
            AND IsDeleted=False AND RecordTypeId IN ('01241000001EgMRAA0','01241000001EgMSAA0','01241000001EgMTAA0') 
           """.format(','.join(fields))

        result_task = sf.bulk.Opportunity.query(query)

        # Convert CreatedDate from timestamp to datetime format
        for task in result_task:
            task['CreatedDate'] = normalize_date(task['CreatedDate'])

        # create an empty list to store the data
        task_list1 = []
        for record in result_task:
            row = [record[field] for field in fields]
            task_list1.append(row)

        # Insert the data into the database
        cursor.executemany("INSERT INTO Extraer_OportunidadesU4O ({}) VALUES ({})".format(','.join(fields), ','.join(
            ['?' for _ in fields])), task_list1)
        cursor.commit()

    except SalesforceMalformedRequest as e:
        print("Malformed Salesforce request:", e)


def extract_advisors(sf, cursor):
    try:
        cursor.execute("SELECT DISTINCT OwnerId FROM Extraer_OportunidadesU4O")
        id_list = [str(row[0]) for row in cursor.fetchall()]

        # Fields to extract from Task object in Salesforce
        fields = ['Id', 'Name', 'Email', 'ManagerId']

        query = """SELECT {} FROM User WHERE Id IN ({})""".format(','.join(fields), ','.join(["'" + i + "'" for i in id_list]))
        result = sf.query_all(query, id_list)['records']

        task_list = [[record['Id'], record['Name'], record['Email'], record['ManagerId']] for record in result]

        cursor.executemany(
            "INSERT INTO Extraer_AsesoresU4O (Id, Name, Email, ManagerId) VALUES (?,?,?,?)",
            task_list
        )
        cursor.commit()

    except SalesforceMalformedRequest as e:
        print("Malformed Salesforce request:", e)


def main(origen):
    start_time = datetime.now()
    conn_sql_server = None
    cursor = None

    try:
        sf = Conexiones.connect_SF(origen)
        conn_sql_server, cursor = Conexiones.connect_ETL_local_sql(origen)

        # Fields to extract from Task object in Salesforce
        fields_opportunities = [
            'Tipo_de_moneda__c', 'CurrencyIsoCode', 'Amount', 'VEC_Campus_de_usuario_del__c',
            'Name', 'CloseDate', 'Probability', 'CreatedDate', 'StageName', 'VEC_CeCo__c',
            'VEC_BusinessContact__c', 'VEC_Motivo_Cerrada_perdida__c', 'Id', 'VEC_ID_Oportunidad__c',
            'AccountId', 'OwnerId', 'VEC_Area_tematica__c', 'RecordTypeId',
            'VEC_Coordinador_academico1__c', 'VEC_TimeCourse__c', 'VEC_Participants__c', 'VEC_Inicio_CeCo__c',
            'VEC_Fin_Ceco__c', 'VEC_Folio_Servicio__c', 'VEC_Problems__c', 'VEC_ProgramType__c',
            'Description', 'VEC_Desarrollador_de_solucion__c', 'VEC_Zona_de_impacto__c', 'VEC_Tipo_Iniciativa__c',
            'VEC_OppOrigin__c', 'VEC_Referidos__c', 'VEC_EjecutionStart__c', 'VEC_FinishedExecution__c',
            'VEC_Definicion_de_la_necesidad_Postventa__c', 'VEC_Resultado_esperado_Postventa__c',
            'VEC_Capacidad_de_accion_Postventa__c',
            'VEC_Descripcion_del_impacto_Postventa__c', 'VEC_Impacto_medida_economica_Postventa__c',
            'VEC_Indicador_Postventa__c',
            'VEC_Instrumento_de_medicion_Postventa__c', 'VEC_Frecuencia_de_medicion_Postventa__c',
            'VEC_Fecha_de_seguimiento_Postventa__c',
            'VEC_Es_factible_el_seguimiento_Postventa__c', 'VEC_Tipo_de_impacto_nivel_1_Postventa__c',
            'VEC_Tipo_de_impacto_nivel_2_Postventa__c',
            'VEC_Impacto_nivel_2_Otros_Postventa__c', 'VEC_Medida_Postventa__c', 'VEC_Medida_Otros_Postventa__c',
            'VEC_Documentacion_cumplimiento_Postventa__c',
            'VEC_Escuelas_que_participan__c', 'VEC_Codigo_de_Servicio_del__c', 'VEC_Folio_reflexiona__c',
            'VEC_Campus_ejecucion__c',
            'VEC_Numero_de_participantes_por_grupo__c', 'VEC_Numero_de_grupos__c', 'VEC_Modalidad_1__c',
            'VEC_Modalidad_1_1__c',
            'VEC_Modalidad_2__c', 'VEC_Modalidad_2_2__c', 'VEC_PlaceCourse__c',
            'VEC_Plataforma_de_aprendizaje_de_EC__c',
            'VEC_Medio_sesiones_sincronas__c', 'VEC_Fecha_encuesta_final_cliente__c',
            'VEC_Competencias__c', 'VEC_Trayectorias__c', 'VEC_Subcompetencias__c'
        ]

        print("Delete records")
        delete_records(cursor)
        print("Extract opportunities")
        extract_opportunities(sf, cursor, fields_opportunities)
        print("Extract advisors")
        extract_advisors(sf, cursor)

    except Exception as e:
        print("An error occurred:", e)

    finally:
        if cursor:
            cursor.close()
        if conn_sql_server:
            conn_sql_server.close()
        print('U4O_Extraer_Oportunidades | Tiempo de ejecución :', datetime.now() - start_time)


if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments