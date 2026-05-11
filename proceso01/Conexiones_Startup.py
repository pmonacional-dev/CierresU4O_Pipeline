from datetime import datetime
import Conexiones

def main(dbname):
    startTime = datetime.now()
    print(f'Iniciando intento de conexión en base de datos {dbname} ')

    conexion = ""
    if dbname == "INTELIGENCIA":
        conexion = Conexiones.connect_INTELIGENCIA_saas_sql()
    elif dbname == "PASE":
        conexion = Conexiones.connect_PASE_saas_sql()
    elif dbname == "QLIK":
        conexion = Conexiones.connect_QLIK_saas_sql()

    # ETL Depreciada por migración y ahorro de costos en la nube institucional. ETL Se mantendrá de forma local
    # elif dbname == "ETL":
    #   conexion = Conexiones.connect_ETL_saas_sql()

    print(f'Finalizando intento de conexión en base de datos {dbname} | Tiempo de ejecución: {datetime.now() - startTime}')
    return conexion

if __name__ == "__main__":
    main(None)  # Call main function without passing any arguments