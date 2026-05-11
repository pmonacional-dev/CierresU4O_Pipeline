#-*- coding: utf-8 -*-
"""
Conexión a SQLServer con Python
"""

import pyodbc 

def crear_conexion_sql(bd):
    try:
        
        server = 'www.edatasoluciones.com,8081'
        #bd = 'BD_PMO'
        #server = 'localhost'
        #bd = 'ETL'
        #bd = 'Edata_Qlik'
        user = 'inteligenciavec'
        password = 'inteligencia629$'
        
        conexion = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};'
					  +'SERVER=' + server
					  +';DATABASE=' + bd
					  +';UID=' + user
					  +';PWD=' + password)
        #print("Conexión a SQL Server establecida exitosamente.")
        return conexion
    except Exception as error:

        print("Ocurrió un error al conectar a SQL Server: ", error)
        print("Type: ", type(error))
		#the exception instance
        print("Arguments: ", error.args)
		#arguments stored in .args

        codigo, mensaje = error.args
		#unpack args

        print('Código: ', codigo)
        print('Mensaje: ', mensaje)
        print("........................................................")
        return None
    
def crear_conexion_sql_Edata_Qlik():
    try:
        
        server = 'www.edatasoluciones.com,8081'
        bd = 'Edata_Qlik'
        #server = 'localhost'
        #bd = 'ETL'
        user = 'inteligenciavec'
        password = 'inteligencia629$'
        
        conexion = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};'
					  +'SERVER=' + server
					  +';DATABASE=' + bd
					  +';UID=' + user
					  +';PWD=' + password)
        print("Conexión a SQL Server establecida exitosamente.")
        return conexion
    except Exception as error:

        print("Ocurrió un error al conectar a SQL Server: ", error)
        print("Type: ", type(error))
		#the exception instance
        print("Arguments: ", error.args)
		#arguments stored in .args

        codigo, mensaje = error.args
		#unpack args

        print('Código: ', codigo)
        print('Mensaje: ', mensaje)
        print("........................................................")
        return None

#crear_conexion_sql('BD_PMO')
#crear_conexion_sql_Edata_Qlik()