from datetime import datetime
import Conexiones
import pyodbc
import mysql.connector

def convert_column_value(asesor_value):
    
    if asesor_value in ['Aida Maria Davila']:
        return 'Aida María Davila Gonzalez'    
    
    elif asesor_value in ['Alexis Aguilar', 'Cesar Alexis Aguilar']:
        return 'Cesar Alexis Aguilar Herrera'
 
    elif asesor_value in ['Ana karen Zamora', 'Karen Maria Zamora']:
        return 'Karen María Zamora Alvarado'     
    
    elif asesor_value in ['ANA LAURA Leon']:
        return 'Ana Laura León Chapa'     
    
    elif asesor_value in ['Andres Segura']:
        return 'Jose Andres Segura Pantoja'  
     
    elif asesor_value in ['Bibiana Alvarado', 'Bibiana Emilia Alvarado']:
        return 'Bibiana Emilia Alvarado Esponda'    
   
    elif asesor_value in ['Brenda Rodriguez', 'Brenda Lourdes Rodriguez']:
        return 'Brenda Lourdes Rodríguez García'     
    
    elif asesor_value in ['Brunela Alejandra Baca']:
        return 'Brunela Alejandra Baca Sánchez'    
   
    elif asesor_value in ['Carlos Ary Legaspi']:
        return 'Carlos Ary Legaspi López'        
   
    elif asesor_value in ['Carlos Jesus Mercadillo', 'Carlos Mercadillo']:
        return 'Carlos Jesús Mercadillo Rojo'
    
    elif asesor_value in ['Catalina Vallin']:
        return 'Catalina Vallin Rojas'        
    
    elif asesor_value in ['Claudia Ariza']:
        return 'Claudia Maritza Ariza'
    
    elif asesor_value in ['Cristina del Carmen Tanus']:
        return 'Cristina del Carmen Tanus Barquín'       
    
    elif asesor_value in ['David Antonio Leith', 'David Leith']:
        return 'David Antonio Leith Ramírez'      
    
    elif asesor_value in ['Diana Constanza Betancourt']:
        return 'Diana Constanza Betancourt Galindo'      

    elif asesor_value in ['Edgar Enrique Borrego']:
        return 'Edgar Enrique Borrego Hernández'         
    
    elif asesor_value in ['Emmanuel Jacome']:
        return 'Emmanuel Jácome Martin'    
    
    elif asesor_value in ['Elvira Toba']:
        return 'Elvira Toba Mery'  
    
    elif asesor_value in ['Erika Alexandra Cedeno']:
        return 'Erika Alexandra Cedeño Cobeña'       
 
    elif asesor_value in ['Esperanza Martinez']:
        return 'Esperanza Martínez Torres'      
    
    elif asesor_value in ['Eunice Eugenia Gongora']:
        return 'Eunice Eugenia Gongora Caballero'   
      
    elif asesor_value in ['Fermin Mojica', 'Fermín Martínez','Fermin Martinez']:
        return 'Fermín Fernando Mojica Araujo'
    
    elif asesor_value in ['Fernando Teran']:
        return 'Fernando Terán Escobar'     
    
    elif asesor_value in ['Geovannina Chavez']:
        return 'Geovannina Chavez Meza'   
    
    elif asesor_value in ['Irma Hurtado']:
        return 'Irma Hurtado Giles'    
    
    elif asesor_value in ['Javier Alejandro Rivera', 'Javier Rivera']:
        return 'Javier Alejandro Rivera Hernández'     
    
    elif asesor_value in ['Jose Abraham Lira']:
        return 'José Abraham Lira Ruiz'   
    
    elif asesor_value in ['Jose Luis Gonzalez']:
        return 'José Luis González Jiménez'
    
    elif asesor_value in ['Juan Pablo Adame']:
        return 'Juan Pablo Adame Arnedo'  
    
    elif asesor_value in ['Julia Belen Ordonez']:
        return 'Julia Belen Ordoñez Ypanaque'    
  
    elif asesor_value in ['Karla Fabiola Escobedo', 'Karla Fabiola Escobedo Soto',
                          'karla Fabiola Escobedo','Karla Escobedo']:
        return 'Karla Fabiola Escobedo Soto'    

    elif asesor_value in ['Karla Maria Ortegon']:
        return 'Karla Maria Ortegon Abud'     

    elif asesor_value in ['KARLA MELIZA CASTRO', 'KARLA MELIZA Meliza CASTRO']:
         return 'Karla Meliza Castro Pérez'    

    elif asesor_value in ['Laura Elisa Escobedo']:
        return 'Laura Elisa Escobedo Torres' 

    elif asesor_value in ['Laura Alvarez', 'Laura Benitez', 'Laura Patricia Alvarez']:
        return 'Laura Patricia Alvarez Benítez' 
    
    elif asesor_value in ['Linda Marybel Hostos', 'Linda Hostos Duran','Linda Ostos Duran']:
        return 'Linda Marybel Hostos Durán'   
    
    elif asesor_value in ['Luisa Lorena Zamora']:
        return 'Luisa Lorena Zamora Marín'      
    
    elif asesor_value in ['Luis Alfonso Montiel', 'Alfonso Montiel']:
        return 'Alfonso Montiel Ríos'     
    
    elif asesor_value in ['Luis Alonso Alonso Hernandez', 'Luis Alonso Hernandez']:
        return 'Luis Alonso Hernández Vázquez'      
    
    elif asesor_value in ['Luis Antonio Sanchez', 'Luis Antonio Antonio Sanchez Portillo']:
        return 'Luis Antonio Sánchez Portillo' 
    
    elif asesor_value in ['Luis Ayala', 'Jorge Luis Ayala']:
        return 'Luis Ayala Medina'      
    
    elif asesor_value in ['Luz Deyanira Vanzulli']:
        return 'Luz Deyanira Vanzulli Carrasco'  
    
    elif asesor_value in ['Luz Maria Padilla']:
        return 'Luz María Padilla Rodríguez'      
    
    elif asesor_value in ['Ma. Eugenia Villaseca']:
        return 'Ma. Eugenia Villaseca Barradas'     
    
    elif asesor_value in ['Maria Irene Ramos']:
        return 'María Irene Ramos Ayala'     
    
    elif asesor_value in ['Ma. Margarita Teran']:
        return 'María Margarita Terán Gómez'     
    
    elif asesor_value in ['Marian Martinez']:
        return 'Marian Martínez Dávila'      
    
    elif asesor_value in ['Monica Mayen']:
        return 'Monica Mayen Sosa'      
    
    elif asesor_value in ['Maria Del Pilar Contreras Gelvez', 'Maria del Pilar Contreras']:
        return 'María del Pilar Contreras Gelves'  
    
    elif asesor_value in ['Maria Sanchez']:
        return 'María Elda Sánchez Cerecedo'      
    
    elif asesor_value in ['Marisol Ojeda', 'Marisol Guadalupe Ojeda']:
        return 'Marisol Guadalupe Ojeda Pérez'   
    
    elif asesor_value in ['Nallely Abril Jaime', 'Nallely Abril Jaime Chavez']:
        return 'Nallely Abril Jaime Chávez'   
    
    elif asesor_value in ['Oscar Javier Castelo']:
        return 'Oscar Javier Castelo Zazueta'   
    
    elif asesor_value in ['Pablo Jair Elias']:
        return 'Pablo Jair Elías González'     
    
    elif asesor_value in ['Paola Ramos']:
        return 'Paola Ramos Galván'       
    
    elif asesor_value in ['Paola Rubio']:
        return 'Paola Rubio Espinosa'   
    
    elif asesor_value in ['Ricardo Cueva', 'Ricardo Cuevas']:
        return 'Ricardo Cueva Acosta'      
    
    elif asesor_value in ['Ricardo Mata']:
        return 'Ricardo Mata Domínguez'    
    
    elif asesor_value in ['Rodrigo Leon']:
        return 'Rodrigo Alberto León Salazar'   
 
    elif asesor_value in ['Santiago Siller']:
        return 'Santiago Siller Cantú'       
    
    elif asesor_value in ['Tania de la Vega']:
        return 'Tania de la Vega Espinal'     
    
    elif asesor_value in ['Teresa Moreno Villaseñor', 'Teresa Norma Moreno',
                          'Teresa Norma Norma Moreno','Teresa Moreno Villasenor']:
        return 'Teresa Norma Moreno Villaseñor'      
 
    elif asesor_value in ['Yael Serna']:
        return 'Yael Serna Mellado'    
    
    return asesor_value


# Main function
def main(origen):
    startTime = datetime.now()
    
    # Initialize variables
    chunk_size = 5000
    offset = 0   
    contadoreliminar = 0
    
    # Establish the connection
    try:
        mysql_connection, mysql_cursor, mysql_table = Conexiones.connect_POSGRADOSU4P_mysql()

        sf = Conexiones.connect_SF(origen)
        conn_sql_server, sql_cursor = Conexiones.connect_ETL_local_sql(origen)

        # Specify the columns in the SELECT statement
        select_columns = """
            id, status, fecha, id_hubspot, id_salesforce, nombre_completo, correo,
            telefono, region, campus, programa, nacionalidad, comentarios, empresa,
            ultimo_año_estudios, codigo_referido, asesor_u4o, correo_asesor_u4o, asesor_u4a,
            correo_asesor_u4a, status_sf, estatus_integrado, propietario, nombre,
            apellido_paterno, campus_indicador, comercializa, periodo, fecha_de_creación,
            origen, escuela, proveedor, estatus, fecha_de_modificación, modalidad,
            modificado_por, total_llamadas, total_tareas, total_correos, actividades,
            causa_descarte, objecion, objecion_dominante_llamadas, año_de_creacion, matricula,
            region_asesor, `tipo_p/c`, siglas_de_la_escuela, antiguedad, año_fecha_de_creacion,
            periodo_integrado, year_periodo, periodo_focalizacion, referido_por, promedio,
            referido_u4o
        """
    
        while True:
            # Execute a query to select rows in chunks
            query = f"SELECT {select_columns} FROM {mysql_table} LIMIT {chunk_size} OFFSET {offset}"
            mysql_cursor.execute(query)
            mysql_rows = mysql_cursor.fetchall()
            
            # Check if there are records
            
            if len(mysql_rows) > 0 and contadoreliminar == 0:
                print("Eliminar el historial de leads de posgrados desde U4O")
                try:
                    # Delete history of TLG components
                    sql_cursor.execute("DELETE FROM Extraer_Posgrados_U4O")         
                    # Commit the changes
                    conn_sql_server.commit()
                    print("Registros de posgrados desde U4O eliminados")   
                    contadoreliminar = 1
                except Exception as delete_error:
                    print(f"Error en eliminación de registros: {delete_error}")    
            
        
            if not mysql_rows:
                print("No more rows to fetch.")
                break  # No more rows to fetch, break out of the loop
                
            # Process the fetched rows (e.g., insert into SQL Server)
            for mysql_row in mysql_rows:
                
                # Convert the tuple to a list for modification
                mysql_row_list = list(mysql_row)                
                    
                # Replace values in the 'asesor_u4o' column
                index_asesor_u4o = mysql_cursor.column_names.index('asesor_u4o')
                mysql_row_list[index_asesor_u4o] = convert_column_value(mysql_row_list[index_asesor_u4o])
    
                # Replace values in the 'referido_por' column
                index_referido_por = mysql_cursor.column_names.index('referido_por')
                mysql_row_list[index_referido_por] = convert_column_value(mysql_row_list[index_referido_por])
    
                # Convert the list back to a tuple
                mysql_row = tuple(mysql_row_list)
                
                # Define the SQL query for insertion into SQL Server
                insert_query = """
                INSERT INTO Extraer_Posgrados_U4O (
                    id, status, fecha, id_hubspot, id_salesforce, nombre_completo, correo,
                    telefono, region, campus, programa, nacionalidad, comentarios, empresa,
                    ultimo_año_estudios, codigo_referido, asesor_u4o, correo_asesor_u4o, asesor_u4a,
                    correo_asesor_u4a, status_sf, estatus_integrado, propietario, nombre,
                    apellido_paterno, campus_indicador, comercializa, periodo, fecha_de_creación,
                    origen, escuela, proveedor, estatus, fecha_de_modificación, modalidad,
                    modificado_por, total_llamadas, total_tareas, total_correos, actividades,
                    causa_descarte, objecion, objecion_dominante_llamadas, año_de_creacion, matricula,
                    region_asesor, tipo_pc, siglas_de_la_escuela, antiguedad, año_fecha_de_creacion,
                    periodo_integrado, year_periodo, periodo_focalizacion, referido_por, promedio,
                    referido_u4o
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """  
        
                # Verify that there is data to insert
                if mysql_row:
                    # Insert each row from MySQL into SQL Server
                    sql_cursor.execute(insert_query, *mysql_row)
                        
            offset += chunk_size
    
            # Commit the changes
            conn_sql_server.commit()
            print("Data inserted successfully.")
      
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