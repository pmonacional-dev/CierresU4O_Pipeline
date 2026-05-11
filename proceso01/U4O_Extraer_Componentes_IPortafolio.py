from datetime import datetime
from simple_salesforce.exceptions import SalesforceMalformedRequest
import Conexiones

def normalizeDate(datestring):
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
        except (TypeError, NameError):
            pass     
    return datestring


# Main function
def main(origen):
    start_time = datetime.now()

    # Database connection
    sf = Conexiones.connect_SF(origen)
    conn_sql_server, sql_cursor = Conexiones.connect_ETL_local_sql(origen)

    print("Eliminar el historial de IPortafolio")
    try:
        # Delete history of components
        sql_cursor.execute("DELETE FROM Extraer_IPortafolio")
        conn_sql_server.commit()
    except:
        print("Error en eliminación de registros")

    # Fields to extract from Task object in Salesforce
    fields = [
            'Id', 'VEC_IDiportafolio__c'
    ]

    print("Obtener la lista de oportunidades con componente IPortafolio desde CRM")
    try:
        query = """
            SELECT {} FROM Opportunity
            WHERE VEC_UsasteIportafolioPropuesta__c = 'Si'
            AND VEC_IDiportafolio__c != NULL
           """.format(','.join(fields)).encode('utf-8')

        result_task = sf.bulk.Opportunity.query(query)
        
        # create an empty list to store the data
        task_list1 = []
        for record in result_task:
            row = [record[field] for field in fields]
            task_list1.append(row)

        # Insert the data into the database
        # Insert the data into the database
        sql_cursor.executemany("INSERT INTO Extraer_IPortafolio ({}) VALUES ({})".format(','.join(fields), ','.join(
            ['?' for _ in fields])), task_list1)
        conn_sql_server.commit()
    except SalesforceMalformedRequest as e:
        print("Malformed Salesforce request: {}".format(str(e)))

    finally:
        # Close the cursor and connection for both MySQL and SQL Server
        if sql_cursor:
            sql_cursor.close()
            conn_sql_server.close()  # Close the SQL Server connection

    print('U4O_Extraer_IPortafolio | Tiempo de ejecución :', datetime.now() - start_time)


if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments