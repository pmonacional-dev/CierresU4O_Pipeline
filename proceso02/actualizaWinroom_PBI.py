from Conexion_SQL import crear_conexion_sql

def ejecutar_sp_fix_autocommit():
    conn = crear_conexion_sql('SIN_Data')
    conn.autocommit = True  # importante
    try:
        cursor = conn.cursor()
        cursor.execute("EXEC dbo.spFix_WinRoom_ImagenFunnel_PBI_Ganadas_Anterior_Acumulado;")
        print("SP ejecutado (autocommit).")
    finally:
        conn.close()

def main():
    ejecutar_sp_fix_autocommit()

if __name__ == "__main__":
    main()