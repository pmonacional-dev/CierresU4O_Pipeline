import pyodbc
import mysql.connector
from simple_salesforce import Salesforce
import time

def connect_SF(string):
    sf = ""
    if string == "Erik":
        sf = Salesforce(
            username='esgutierrez@itesm.mx',
            password='aries777',
            security_token='ZSZrcNM3axxa3KKFTT3kKchOs'
        )
    elif string == "Antonio":
        sf = Salesforce(
            #username='esgutierrez@itesm.mx',
            #password='aries777',
            #security_token='ZSZrcNM3axxa3KKFTT3kKchOs'
            username='antoniogj@tec.mx',
            password='240591agj',
            security_token='9qlsHrgpLVvVJ2r5jq1gb1bWM'
        )
    # Update session headers to specify chunk size for data retrieval
    sf.session.headers.update({'Sforce-Transport-Settings': 'chunkSize=5000'})
    return sf


def connect_POSGRADOSU4P_mysql():
    # Replace the placeholder values with your MySQL server information
    host = '34.66.131.38'
    port = '3306'  # Replace with the actual port number
    database = 'vistas_u4o'
    username = 'lectura_u4o'
    password = 'sdqpk_$h%wmnfar^alljon'
    table_name = 'referidos_u4o'

    # Establish the connection
    connection = mysql.connector.connect(
        host=host,
        port=port,
        database=database,
        user=username,
        password=password
    )
    cursor = connection.cursor()
    return connection, cursor, table_name


def connect_TLGU4P_mysql():
    # Replace the placeholder values with your MySQL server information
    host = '34.66.131.38'
    port = '3306'  # Replace with the actual port number
    database = 'vistas_u4o'
    username = 'lectura_u4o'
    password = 'sdqpk_$h%wmnfar^alljon'
    table_name = 'ventas_tlg_u4o'

    # Establish the connection
    connection = mysql.connector.connect(
        host=host,
        port=port,
        database=database,
        user=username,
        password=password
    )
    cursor = connection.cursor()
    return connection, cursor, table_name



# Function to handle database connections ETL Local
def connect_ETL_local_sql(origen):
    # Connect to SQL Server
    conn_sqlserver = None
    if origen == "Erik":
        conn_sqlserver = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=EDATA;DATABASE=ETL;UID=inteligenciavec;PWD=inteligencia629$')
    elif origen == "Antonio":
        conn_sqlserver = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=L03523797L03;DATABASE=ETL;UID=inteligenciavec;PWD=inteligencia629$')
    # Establish credentials for Salesforce and SQL
    cursor = conn_sqlserver.cursor()
    cursor.fast_executemany = True
    return conn_sqlserver, cursor


def connect_SINDATA_local_sql(origen):
    # Connect to SQL Server
    conn_sqlserver = None
    if origen == "Erik":
        conn_sqlserver = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=EDATA;DATABASE=SIN_Data;UID=inteligenciavec;PWD=inteligencia629$')
    elif origen == "Antonio":
        conn_sqlserver = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=L03523797L03;DATABASE=SIN_Data;UID=inteligenciavec;PWD=inteligencia629$')
    # Establish credentials for Salesforce and SQL
    cursor = conn_sqlserver.cursor()
    cursor.fast_executemany = True
    return conn_sqlserver, cursor


def connect_QLIK_saas_sql():
    # Connect to SQL Server
    retries = 0
    max_retries = 3
    retry_interval = 10
    while retries < max_retries:
        try:
            conn_sqlserver = pyodbc.connect(
                'DRIVER={ODBC Driver 17 for SQL Server};SERVER=www.edatasoluciones.com,8081;DATABASE=Edata_Qlik;UID=inteligenciavec;PWD=inteligencia629$;Connection Timeout=120;TrustServerCertificate=yes;')
                #'DRIVER={ODBC Driver 17 for SQL Server};SERVER=edatasql.database.windows.net;DATABASE=Edata_Qlik;UID=inteligenciavec;PWD=inteligencia629$;TrustServerCertificate=yes;Connection Timeout=30')
            cursor = conn_sqlserver.cursor()
            cursor.fast_executemany = True
            return conn_sqlserver, cursor
        except pyodbc.Error as e:
            retries += 1
            print(f"Intento {retries}/{max_retries}: Conexión a QLIK_saas_sql falló")
            if retries < max_retries:
                print(f"Intentando nuevamente en {retry_interval} segundos...")
                time.sleep(retry_interval)  # Move this line here
    print("Máximo número de intentos alcanzado. Database QLIK_saas_sql no fue detectada.")
    return None, None

def connect_SINDATA_saas_sql():
    # Connect to SQL Server
    retries = 0
    max_retries = 3
    retry_interval = 10
    while retries < max_retries:
        try:
            conn_sqlserver = pyodbc.connect(
                'DRIVER={ODBC Driver 17 for SQL Server};SERVER=www.edatasoluciones.com,8081;DATABASE=SIN_Data;UID=inteligenciavec;PWD=inteligencia629$;Connection Timeout=120;TrustServerCertificate=yes;')
            cursor = conn_sqlserver.cursor()
            cursor.fast_executemany = True
            return conn_sqlserver, cursor
        except pyodbc.Error as e:
            retries += 1
            print(f"Intento {retries}/{max_retries}: Conexión a SINDATA_saas_sql falló")
            if retries < max_retries:
                print(f"Intentando nuevamente en {retry_interval} segundos...")
                time.sleep(retry_interval)  # Move this line here
    print("Máximo número de intentos alcanzado. Database SINDATA_saas_sql no fue detectada.")
    return None, None


def connect_INTELIGENCIA_saas_sql():
    # Connect to SQL Server
    retries = 0
    max_retries = 3
    retry_interval = 10
    while retries < max_retries:
        try:
            conn_sqlserver = pyodbc.connect(
                #'DRIVER={ODBC Driver 17 for SQL Server};SERVER=edatasql.database.windows.net;DATABASE=Inteligencia;UID=inteligenciavec;PWD=inteligencia629$;Connection Timeout=120;TrustServerCertificate=yes;')
                'DRIVER={ODBC Driver 17 for SQL Server};SERVER=www.edatasoluciones.com,8081;DATABASE=Inteligencia;UID=inteligenciavec;PWD=inteligencia629$;Connection Timeout=120;TrustServerCertificate=yes;')
            cursor = conn_sqlserver.cursor()
            cursor.fast_executemany = True
            return conn_sqlserver, cursor
        except pyodbc.Error as e:
            retries += 1
            print(f"Intento {retries}/{max_retries}: Conexión a INTELIGENCIA_saas_sql falló")
            if retries < max_retries:
                print(f"Intentando nuevamente en {retry_interval} segundos...")
                time.sleep(retry_interval)  # Move this line here
    print("Máximo número de intentos alcanzado. Database INTELIGENCIA_saas_sql no fue detectada.")
    return None, None


def connect_PASE_saas_sql():
    # Connect to SQL Server
    retries = 0
    max_retries = 3
    retry_interval = 10
    while retries < max_retries:
        try:
            conn_sqlserver = pyodbc.connect(
                'DRIVER={ODBC Driver 17 for SQL Server};SERVER=prod022azsql14.database.windows.net;DATABASE=PASE;UID=Paseappuser;PWD=x4kYyCRj6M5kd6G9;Connection Timeout=120;TrustServerCertificate=yes;')
                #'DRIVER={ODBC Driver 17 for SQL Server};SERVER=pprd022azsql08.database.windows.net;DATABASE=PASE;UID=Paseappuser;PWD=S60oO55Xq3UdNd;Connection Timeout=120;TrustServerCertificate=yes;')
            cursor = conn_sqlserver.cursor()
            cursor.fast_executemany = True
            return conn_sqlserver, cursor
        except pyodbc.Error as e:
            retries += 1
            print(f"Intento {retries}/{max_retries}: Conexión a PASE_saas_sql falló")
            if retries < max_retries:
                print(f"Intentando nuevamente en {retry_interval} segundos...")
                time.sleep(retry_interval)  # Move this line here
    print("Máximo número de intentos alcanzado. Database PASE_saas_sql no fue detectada.")
    return None, None


# Conexión local PMO
#def connect_PMO_saas_sql(origen):
#   # Connect to SQL Server
#    conn_sqlserver = None
#    if origen == "Erik":
#        conn_sqlserver = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=EDATA;DATABASE=BD_PMO;UID=inteligenciavec;PWD=inteligencia629$')
#    elif origen == "Antonio":
#        conn_sqlserver = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER=L03523797L03;DATABASE=BD_PMO;UID=inteligenciavec;PWD=inteligencia629$')
#    # Establish credentials for Salesforce and SQL
#    cursor = conn_sqlserver.cursor()
#    cursor.fast_executemany = True
#    return conn_sqlserver, cursor

# Conexión SaaS PMO
def connect_PMO_saas_sql(origen):
    # Connect to SQL Server
    retries = 0
    max_retries = 3
    retry_interval = 10
    while retries < max_retries:
        try:
            conn_sqlserver = pyodbc.connect(
                #'DRIVER={ODBC Driver 17 for SQL Server};SERVER=edatasql.database.windows.net;DATABASE=Inteligencia;UID=inteligenciavec;PWD=inteligencia629$;Connection Timeout=120;TrustServerCertificate=yes;')
                'DRIVER={ODBC Driver 17 for SQL Server};SERVER=www.edatasoluciones.com,8081;DATABASE=BD_PMO;UID=inteligenciavec;PWD=inteligencia629$;Connection Timeout=120;TrustServerCertificate=yes;')
            cursor = conn_sqlserver.cursor()
            cursor.fast_executemany = True
            return conn_sqlserver, cursor
        except pyodbc.Error as e:
            retries += 1
            print(f"Intento {retries}/{max_retries}: Conexión a PMO_saas_sql falló")
            if retries < max_retries:
                print(f"Intentando nuevamente en {retry_interval} segundos...")
                time.sleep(retry_interval)  # Move this line here
    print("Máximo número de intentos alcanzado. Database PMO_saas_sql no fue detectada.")
    return None, None