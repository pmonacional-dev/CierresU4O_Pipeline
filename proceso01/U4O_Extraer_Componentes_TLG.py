import unicodedata
from datetime import datetime
from simple_salesforce.exceptions import SalesforceMalformedRequest
import pyodbc
from decimal import Decimal
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
                # datestring = datestring.strftime('%Y-%m-%d')
                datestring = str(datestring)
        except (TypeError, NameError):  # unicode is a default on python 3
            pass
    return datestring


# Main function
def main(origen):
    startTime = datetime.now()
    
    # Database connection
    sf = Conexiones.connect_SF(origen)
    conn_sql_server, sql_cursor = Conexiones.connect_ETL_local_sql(origen)
    
    print("Eliminar el historial de componentes TLG")
    try:
        # Delete history of TLG components
        sql_cursor.execute("DELETE FROM Extraer_TLG_Componente")
        # Delete history of TLG percentage
        sql_cursor.execute("DELETE FROM Extraer_TLG_Porcentaje")
        sql_cursor.commit()
    except:
        print("Error en eliminación de registros")
    
    # Fields to extract from Task object in Salesforce
    fields = [
        'Id', 'VEC_Tipo_Iniciativa__c', 'VEC_Trayectorias__c', 'VEC_Competencias__c', 'VEC_Subcompetencias__c',
        'VEC_Modalidad_1__c',
        'VEC_Modalidad_2__c',
        'VEC_ModalidadTres__c',
        'VEC_ModalidadCuatro__c',
        'VEC_ModalidadCinco__c',
        'VEC_Modalidad_1_1__c',
        'VEC_Modalidad_2_2__c',
        'VEC_PorcentajeModalidadTres__c',
        'VEC_PorcentajeModalidadCuatro__c',
        'VEC_PorcentajeModalidadCinco__c'
        ]
    
    print("Obtener la lista de oportunidades con componente TLG desde CRM")
    try:
        query = """
            SELECT {} FROM Opportunity
            WHERE (StageName IN ('Cerrada Ganada','Cerrada Perdida', 'Oportunidad','Propuesta','Negociación')
            AND IsDeleted=False
            AND RecordTypeId IN ('01241000001EgMRAA0','01241000001EgMSAA0','01241000001EgMTAA0')
            AND (VEC_Trayectorias__c !=null OR VEC_Competencias__c !=null  OR VEC_Subcompetencias__c !=null ))
            OR (StageName IN ('Cerrada Ganada','Cerrada Perdida', 'Oportunidad', 'Propuesta', 'Negociación')
            AND IsDeleted=False
            AND RecordTypeId IN ('01241000001EgMRAA0','01241000001EgMSAA0','01241000001EgMTAA0')
            AND VEC_Tipo_Iniciativa__c = 'TLG (The Learning Gate)')
           """.format(','.join(fields)).encode('utf-8')
        
        resultTask = sf.bulk.Opportunity.query(query)
        
        # Check the total number of records returned by the query
        total_records = len(resultTask)
        print(f"Total de registros U4O con componente TLG: {total_records}")
        
        # List to store Opportunity IDs
        opportunity_ids = []
        for record in resultTask:
            # Extract Opportunity ID and add it to the list
            opportunity_id = record['Id']
            opportunity_ids.append(opportunity_id)
        
        # Print or use the list of Opportunity IDs
        # print("List of Opportunity IDs:", opportunity_ids)
        
        # Check if the list is not empty before executing the SQL query
        if opportunity_ids:
            # Convert Opportunity IDs to a comma-separated string for the IN clause
            opportunity_ids_str = ",".join(["'{}'".format(opp_id) for opp_id in opportunity_ids])
            
            # Define the SQL query for retrieving records from Extraer_OportunidadesU4O
            select_query = f"""
                SELECT Id, Amount
                FROM Extraer_OportunidadesU4O
                WHERE Id IN ({opportunity_ids_str})
            """
            
            try:
                # Execute the SQL query
                sql_cursor.execute(select_query)
                # Fetch all the records
                result_opportunidades_u4o = sql_cursor.fetchall()
            
            except pyodbc.Error as e:
                print("Error querying Extraer_OportunidadesU4O: {}".format(str(e)))
            
            # Fetch Opportunity IDs and Amounts from Salesforce
            opportunity_data = []
            for record in resultTask:
                opportunity_id = record['Id']
                opportunity_Modalidad_1 = record['VEC_Modalidad_1__c']
                opportunity_Modalidad_2 = record['VEC_Modalidad_2__c']
                opportunity_Modalidad_3 = record['VEC_ModalidadTres__c']
                opportunity_Modalidad_4 = record['VEC_ModalidadCuatro__c']
                opportunity_Modalidad_5 = record['VEC_ModalidadCinco__c']
                
                opportunity_PorcentajeModalidad_1 = record['VEC_Modalidad_1_1__c']
                opportunity_PorcentajeModalidad_2 = record['VEC_Modalidad_2_2__c']
                opportunity_PorcentajeModalidad_3 = record['VEC_PorcentajeModalidadTres__c']
                opportunity_PorcentajeModalidad_4 = record['VEC_PorcentajeModalidadCuatro__c']
                opportunity_PorcentajeModalidad_5 = record['VEC_PorcentajeModalidadCinco__c']
                
                amount = next((row.Amount for row in result_opportunidades_u4o if row.Id == opportunity_id), None)
                
                # Check if amount is None before performing any arithmetic operations
                if amount is None:
                    amount = 0
                
                TLG_Amount = amount
                # print(amount);
                # print(TLG_Amount);
                # Initialize TLG_Percentage with a default value
                TLG_Percentage = "0"
                
                # Check if Modalidad1 is equal to "Learning Gate"
                if opportunity_Modalidad_1 == "Learning Gate":
                    # Check if PorcentajeModalidad1 is not None
                    if opportunity_PorcentajeModalidad_1 is None:
                        opportunity_PorcentajeModalidad_1 = "100"
                    
                    try:
                        TLG_Percentage = opportunity_PorcentajeModalidad_1
                        percentage = float(opportunity_PorcentajeModalidad_1.strip('%')) / 100.0
                        TLG_Amount = float(TLG_Amount)  # Convert amount to float
                        TLG_Amount *= percentage
                        TLG_Amount = Decimal(TLG_Amount)  # Convert back to Decimal
                        amount = amount - TLG_Amount
                    except ValueError:
                        print("Error converting PorcentajeModalidad1 to a float for Opportunity ID: {}".format(
                            opportunity_id))
                
                # Check if Modalidad2 is equal to "Learning Gate"
                elif opportunity_Modalidad_2 == "Learning Gate":
                    # Check if PorcentajeModalidad2 is not None
                    if opportunity_PorcentajeModalidad_2 is None:
                        opportunity_PorcentajeModalidad_2 = "100"
                    
                    try:
                        TLG_Percentage = opportunity_PorcentajeModalidad_2
                        percentage = float(opportunity_PorcentajeModalidad_2.strip('%')) / 100.0
                        TLG_Amount = float(TLG_Amount)  # Convert amount to float
                        TLG_Amount *= percentage
                        TLG_Amount = Decimal(TLG_Amount)  # Convert back to Decimal
                        amount = amount - TLG_Amount
                    except ValueError:
                        print("Error converting PorcentajeModalidad1 to a float for Opportunity ID: {}".format(
                            opportunity_id))
                
                
                
                # Check if Modalidad3 is equal to "Learning Gate"
                elif opportunity_Modalidad_3 == "Learning Gate":
                    # Check if PorcentajeModalidad2 is not None
                    if opportunity_PorcentajeModalidad_3 is None:
                        opportunity_PorcentajeModalidad_3 = "100"
                    
                    try:
                        TLG_Percentage = opportunity_PorcentajeModalidad_3
                        percentage = float(opportunity_PorcentajeModalidad_3.strip('%')) / 100.0
                        TLG_Amount = float(TLG_Amount)  # Convert amount to float
                        TLG_Amount *= percentage
                        TLG_Amount = Decimal(TLG_Amount)  # Convert back to Decimal
                        amount = amount - TLG_Amount
                    except ValueError:
                        print("Error converting PorcentajeModalidad1 to a float for Opportunity ID: {}".format(
                            opportunity_id))
                
                
                # Check if Modalidad4 is equal to "Learning Gate"
                elif opportunity_Modalidad_4 == "Learning Gate":
                    # Check if PorcentajeModalidad2 is not None
                    if opportunity_PorcentajeModalidad_4 is None:
                        opportunity_PorcentajeModalidad_4 = "100"
                    
                    try:
                        TLG_Percentage = opportunity_PorcentajeModalidad_4
                        percentage = float(opportunity_PorcentajeModalidad_4.strip('%')) / 100.0
                        TLG_Amount = float(TLG_Amount)  # Convert amount to float
                        TLG_Amount *= percentage
                        TLG_Amount = Decimal(TLG_Amount)  # Convert back to Decimal
                        amount = amount - TLG_Amount
                    except ValueError:
                        print("Error converting PorcentajeModalidad1 to a float for Opportunity ID: {}".format(
                            opportunity_id))
                
                
                
                # Check if Modalidad5 is equal to "Learning Gate"
                elif opportunity_Modalidad_5 == "Learning Gate":
                    # Check if PorcentajeModalidad2 is not None
                    if opportunity_PorcentajeModalidad_5 is None:
                        opportunity_PorcentajeModalidad_5 = "100"
                    
                    try:
                        TLG_Percentage = opportunity_PorcentajeModalidad_5
                        percentage = float(opportunity_PorcentajeModalidad_5.strip('%')) / 100.0
                        TLG_Amount = float(TLG_Amount)  # Convert amount to float
                        TLG_Amount *= percentage
                        TLG_Amount = Decimal(TLG_Amount)  # Convert back to Decimal
                        amount = amount - TLG_Amount
                    except ValueError:
                        print("Error converting PorcentajeModalidad1 to a float for Opportunity ID: {}".format(
                            opportunity_id))
                
                
                
                # Case when opportunity_Modalidad_2 is None and opportunity_Modalidad_1 is not "Learning Gate"
                else:
                    TLG_Percentage = "0"
                    TLG_Amount = 0
                
                # Append the data to the opportunity_data list
                opportunity_data.append({
                    'Id': opportunity_id,
                    'NonTLG_Amount': amount,
                    'TLG_Amount': TLG_Amount,
                    'TLG_Percentage': TLG_Percentage
                    })
            
            """
            # Print or use the data as needed
            for data in opportunity_data:
                print("Opportunity ID: {}, NonTLG_Amount: {}, TLG_Amount: {}, TLG_Percentage: {}"
                      .format(data['Id'], data['NonTLG_Amount'], data['TLG_Amount'], data['TLG_Percentage']))
            """
        
        # Define the SQL query for insertion
        insert_query = "INSERT INTO Extraer_TLG_Porcentaje (Id, NonTLG_Amount, TLG_Amount, TLG_Percentage) VALUES (?, ?, ?, ?)"
        
        # Prepare the data for insertion
        data_to_insert = [
            (str(data['Id']), float(data['NonTLG_Amount']), float(data['TLG_Amount']), str(data['TLG_Percentage']))
            for data in opportunity_data
            ]
        
        # Execute the insertion query with executemany
        sql_cursor.executemany(insert_query, data_to_insert)
        
        # Commit the changes to the database
        sql_cursor.commit()
        
        """
        # Print or use the data as needed
        for data in opportunity_data:
            print("Opportunity ID: {}, Modalidad1: {}, PorcentajeModalidad1: {}  , Modalidad2: {}, PorcentajeModalidad2: {}  , NonTLG_Amount: {}, TLG_Amount: {}"
                  .format(data['Id'], data['Modalidad1'], data['PorcentajeModalidad1'] ,data['Modalidad2'], data['PorcentajeModalidad2']
                          , data['NonTLG_Amount'], data['TLG_Amount']))
        """
        
        # create an empty list to store the data
        task_list = []
        registro_tlg = []
        lista_elementos_tlg = []
        
        for record in resultTask:
            row = [record[field] for field in fields]
            task_list.append(row)
            
            # Check if 'VEC_Trayectorias__c' field exists in record
            if record['VEC_Trayectorias__c'] is not None:
                # Check if ';' is present in the VEC_Trayectorias__c field
                if ';' in record['VEC_Trayectorias__c']:
                    # Count the number of symbols
                    symbol_count = record['VEC_Trayectorias__c'].count(';')
                    
                    # Save the relevant information
                    opportunity_info = {
                        'Id': record['Id'],
                        'Symbol_Count': symbol_count + 1,
                        'Nomenclatura': record['VEC_Trayectorias__c'],
                        'Tipo_Componente': 'Trayectoria'  # You can customize this label as needed
                        }
                    
                    registro_tlg.append(opportunity_info)
                
                # Check if ';' is not present and VEC_Trayectorias__c is not None
                else:
                    # Save the relevant information
                    opportunity_info = {
                        'Id': record['Id'],
                        'Symbol_Count': 1,
                        'Nomenclatura': record['VEC_Trayectorias__c'],
                        'Tipo_Componente': 'Trayectoria'  # You can customize this label as needed
                        }
                    
                    registro_tlg.append(opportunity_info)
            
            # Check if 'VEC_Competencias__c' field exists in record
            if record['VEC_Competencias__c'] is not None:
                # Check if ';' is present in the VEC_Competencias__c field
                if ';' in record['VEC_Competencias__c']:
                    # Count the number of symbols
                    symbol_count = record['VEC_Competencias__c'].count(';')
                    
                    # Save the relevant information
                    opportunity_info = {
                        'Id': record['Id'],
                        'Symbol_Count': symbol_count + 1,
                        'Nomenclatura': record['VEC_Competencias__c'],
                        'Tipo_Componente': 'Competencia'  # You can customize this label as needed
                        }
                    
                    registro_tlg.append(opportunity_info)
                
                # Check if ';' is not present and VEC_Competencias__c is not None
                else:
                    # Save the relevant information
                    opportunity_info = {
                        'Id': record['Id'],
                        'Symbol_Count': 1,
                        'Nomenclatura': record['VEC_Competencias__c'],
                        'Tipo_Componente': 'Competencia'  # You can customize this label as needed
                        }
                    
                    registro_tlg.append(opportunity_info)
            
            # Check if 'VEC_Subcompetencias__c' field exists in record
            if record['VEC_Subcompetencias__c'] is not None:
                # Check if ';' is present in the VEC_Competencias__c field
                if ';' in record['VEC_Subcompetencias__c']:
                    # Count the number of symbols
                    symbol_count = record['VEC_Subcompetencias__c'].count(';')
                    
                    # Save the relevant information
                    opportunity_info = {
                        'Id': record['Id'],
                        'Symbol_Count': symbol_count + 1,
                        'Nomenclatura': record['VEC_Subcompetencias__c'],
                        'Tipo_Componente': 'Subcompetencia'  # You can customize this label as needed
                        }
                    
                    registro_tlg.append(opportunity_info)
                
                # Check if ';' is not present and VEC_Subcompetencias__c is not None
                else:
                    # Save the relevant information
                    opportunity_info = {
                        'Id': record['Id'],
                        'Symbol_Count': 1,
                        'Nomenclatura': record['VEC_Subcompetencias__c'],
                        'Tipo_Componente': 'Subcompetencia'  # You can customize this label as needed
                        }
                    
                    registro_tlg.append(opportunity_info)
                    
                    # Define the order of Tipo_Componente values
        tipo_componente_order = {"Trayectoria": 1, "Competencia": 2, "Subcompetencia": 3}
        
        # Sorting the registro_tlg list by Tipo_Componente, Trayectoria, Competencias, and Subcompetencias
        sorted_registro_tlg = sorted(registro_tlg, key=lambda x: (tipo_componente_order.get(x['Tipo_Componente'])))
        
        # Imprimir todas las oportunidades en donde existe una coincidencia de registro de componente TLG+
        """
        for opportunity_info in sorted_registro_tlg:
            print("Opportunity ID: {}, Symbol Count: {}, Componente: {}, Tipo_Componente: {}".format(
                opportunity_info['Id'], opportunity_info['Symbol_Count'],
                opportunity_info['Nomenclatura'], opportunity_info['Tipo_Componente']
            ))
        """
        
        for opportunity_info in sorted_registro_tlg:
            if opportunity_info['Symbol_Count'] == 1:
                # Create a new dictionary with selected fields and add it to the filtered list
                filtered_record = {
                    'Id': opportunity_info['Id'],
                    'Nomenclatura': opportunity_info['Nomenclatura'],
                    'Tipo_Componente': opportunity_info['Tipo_Componente']
                    }
                lista_elementos_tlg.append(filtered_record)
            else:
                # For Symbol_Count greater than 1, split Componente based on ';' and iterate
                components = opportunity_info['Nomenclatura'].split(';')
                for component in components:
                    # Create a new dictionary for each component and add it to the filtered list
                    filtered_record = {
                        'Id': opportunity_info['Id'],
                        'Nomenclatura': component.strip(),  # Remove leading/trailing whitespaces
                        'Tipo_Componente': opportunity_info['Tipo_Componente']
                        }
                    lista_elementos_tlg.append(filtered_record)
        
        """
        # Imprimir la identificación individual de componentes existentes en una oportunidad
        for record in lista_elementos_tlg:
            print("Filtered Record - Opportunity ID: {}, Nomenclatura: {}, Tipo_Componente: {}".format(
                record['Id'], record['Nomenclatura'], record['Tipo_Componente']
            ))
        """
        
        # Define the SQL query for insertion
        insert_query = "INSERT INTO Extraer_TLG_Componente (Id, Tipo_Componente, Nomenclatura) VALUES (?, ?, ?)"
        # Prepare the data for insertion, handling Subcompetencias string splitting
        data_to_insert = [(record['Id'], record['Tipo_Componente'], record['Nomenclatura']) for record in
                          lista_elementos_tlg if record['Tipo_Componente']
                          in ('Trayectoria', 'Competencia', 'Subcompetencia')]
        # Execute the insertion query with executemany
        sql_cursor.executemany(insert_query, data_to_insert)
        # Commit the changes to the database
        sql_cursor.commit()
    
    except SalesforceMalformedRequest as e:
        print("Malformed Salesforce request: {}".format(str(e)))
    
    finally:
        # Close the cursor and connection for both MySQL and SQL Server
        if sql_cursor:
            sql_cursor.close()
            conn_sql_server.close()  # Close the SQL Server connection


if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments