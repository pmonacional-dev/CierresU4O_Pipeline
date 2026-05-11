"""
Script para calcular e insertar importes mensuales devengados de proyectos PMO.

Este proceso realiza las siguientes tareas:
1. Obtiene los datos desde SQL Server o desde un archivo Excel.
2. Ajusta las fechas de inicio y fin para que siempre sean el primer día del mes.
3. Calcula los importes mensuales distribuidos entre los meses del proyecto.
4. Exporta los resultados a un archivo Excel.
5. Inserta los datos procesados en la tabla `ETL_Extraer_Importe_Gestionado` de SQL Server.

Requisitos:
- Tener acceso a la base de datos SQL Server y el módulo `crear_conexion_sql`.
- Librerías necesarias: pandas, openpyxl, tqdm, dateutil

Estructura esperada en el archivo Excel:
- "Fecha de Inicio"
- "Fecha de Termino"
- "id CRM"
- "Region"
- "Importe de Venta CRM"
- "Gestor del Proyecto"
- "Nombre Proyecto"
- "ImportePorGestionar" → valores "TRUE" o "FALSE"

Tabla destino en SQL Server: `ETL_Extraer_Importe_Gestionado`
Columnas:
- id_crm (varchar)
- region (varchar)
- gestor (varchar)
- programa (varchar)
- num_mes_gestionar (int)
- fecha_gestionar (date)
- importe_gestionar (float)
- aplica_importe_gestion (bit)
- usuario_actualizo (varchar)
- fecha_actualizo (date)

Autor: Antonio Guerrero 
Fecha de actualización: 05-09-2025
"""

from Conexion_SQL           import crear_conexion_sql
from datetime               import datetime, timedelta
from dateutil.relativedelta import relativedelta
from tqdm                   import tqdm
from concurrent.futures     import ThreadPoolExecutor
from datetime               import datetime
from concurrent.futures     import ThreadPoolExecutor
import numpy  as np
import pandas as pd
import threading
import os

def es_verdadero(valor):
    """
    Normaliza y evalúa si un valor representa un 'verdadero' lógico.
    """
    if isinstance(valor, bool):
        return valor is True
    if isinstance(valor, (int, float)):
        return valor == 1 or valor == 1.0
    if isinstance(valor, str):
        return valor.strip().upper() in {'VERDADERO', 'TRUE', '1', '1.0'}
    return False

def obtener_datos(origen="excel", archivo_excel="dat_AsignacionesGestion.xlsx"):
    """
    Obtiene los datos desde SQL Server o desde un archivo Excel.
    Usa rutas absolutas basadas en la ubicación del script para evitar FileNotFoundError.
    """

    if origen == "sql":
        print("Obteniendo datos desde SQL Server...")
        conn = crear_conexion_sql('BD_PMO')
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fecha_inicio, fecha_fin, id_crm, region, importe_venta
            FROM Datos_CRM
            WHERE fecha_inicio IS NOT NULL AND fecha_fin IS NOT NULL
        """)

        registros = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        df = pd.DataFrame.from_records(registros, columns=columns)
        conn.close()
    else:
        # Obtiene la carpeta donde reside este script y busca en subcarpeta data/
        directorio_actual = os.path.dirname(os.path.abspath(__file__))
        ruta_data = os.path.join(directorio_actual, "data")
        ruta_completa_excel = os.path.join(ruta_data, archivo_excel)

        print(f"Buscando archivo en: {ruta_completa_excel}")

        if not os.path.exists(ruta_completa_excel):
            # Si aún así no existe, listamos los archivos para ver si hay un error de dedo en el nombre
            archivos_en_carpeta = os.listdir(directorio_actual)
            raise FileNotFoundError(
                f"❌ No se encontró '{archivo_excel}' en la carpeta:\n{directorio_actual}\n"
                f"Archivos encontrados en esa carpeta: {archivos_en_carpeta}"
            )

        print(f"📖 Leyendo archivo exitosamente.")
        df = pd.read_excel(ruta_completa_excel)
        
        # Renombrar columnas
        df = df.rename(columns={
            "Fecha_InicioAsignacion":   "fecha_inicio",
            "Fecha_TerminoAsignacion":  "fecha_fin",
            "id_CRM":                   "id_crm",
            "Region":                   "region",
            "ImporteVenta":             "importe_venta",
            "Monto_Gestionado":         "importe_gestion",
            "Gestor_Asignado":          "gestor",
            "Nombre_Proyecto":          "programa",
            "ImportePorGestionar":      "importe_por_gestionar"
        })
        
        # Filtrar registros con valores nulos en fecha_inicio o fecha_fin
        df = df.dropna(subset=["fecha_inicio", "fecha_fin"])

    return df

def obtener_datos_old(origen="excel", archivo_excel="dat_AsignacionesGestion.xlsx"):
    """
    Obtiene los datos desde SQL Server o desde un archivo Excel.
    
    Parámetros:
    - origen (str): 'sql' o 'excel'.
    - archivo_excel (str): ruta al archivo Excel, si se selecciona 'excel'.
    
    Retorna:
    - pd.DataFrame: datos procesados con nombres de columnas estandarizados.
    """
    
    if origen == "sql":
        print("sql")
        conn = crear_conexion_sql('BD_PMO')
        cursor = conn.cursor()
        cursor.execute("""
            SELECT fecha_inicio, fecha_fin, id_crm, region, importe_venta 
            FROM Datos_CRM
            WHERE fecha_inicio IS NOT NULL AND fecha_fin IS NOT NULL
        """)
        
        registros = cursor.fetchall()
        columns = [column[0] for column in cursor.description]
        df = pd.DataFrame.from_records(registros, columns=columns)
        conn.close()
    else:
        """
        Version anterior que funciona con el excel Respaldo_TableroPMO.xlsx
        print(origen)
        df = pd.read_excel(archivo_excel)
        df = df.rename(columns={
            "Fecha de Inicio": "fecha_inicio",
            "Fecha de Termino": "fecha_fin",
            "id CRM": "id_crm",
            "Region": "region",
            "Importe de Venta CRM": "importe_venta",
            "Gestor del Proyecto": "gestor",
            "Nombre Proyecto": "programa",
            "ImportePorGestionar": "importe_por_gestionar",
            "ImportePorGestionar_py": "importe_por_gestionar_py"
        })
        
        # Filtrar registros con valores nulos en fecha_inicio o fecha_fin
        df = df.dropna(subset=["fecha_inicio", "fecha_fin"])
        """

        print(origen)
        df = pd.read_excel(archivo_excel)
        df = df.rename(columns={
            "Fecha_InicioAsignacion":   "fecha_inicio",
            "Fecha_TerminoAsignacion":  "fecha_fin",
            "id_CRM":                   "id_crm",
            "Region":                   "region",
            "ImporteVenta":             "importe_venta",
            "Monto_Gestionado":         "importe_gestion",
            "Gestor_Asignado":          "gestor",
            "Nombre_Proyecto":          "programa",
            "ImportePorGestionar":      "importe_por_gestionar"
        })
        
        # Filtrar registros con valores nulos en fecha_inicio o fecha_fin
        df = df.dropna(subset=["fecha_inicio", "fecha_fin"])

    return df

def ajustar_fechas(df):
    """
    Ajusta las fechas de inicio y fin para que correspondan al primer día del mes.
    
    Parámetros:
    - df (pd.DataFrame): DataFrame con columnas 'fecha_inicio' y 'fecha_fin'.
    
    Retorna:
    - pd.DataFrame: DataFrame con fechas modificadas.
    """
    df['fecha_inicio'] = df['fecha_inicio'].apply(lambda x: x.replace(day=1) if pd.notnull(x) else None)
    df['fecha_fin'] = df['fecha_fin'].apply(lambda x: x.replace(day=1) if pd.notnull(x) else None)
    return df


def generar_importes_gestionado(df):
    """
    Calcula los importes mensuales devengados por proyecto.
    
    Por cada mes dentro del rango de un proyecto, genera una fila con el importe correspondiente.
    
    Parámetros:
    - df (pd.DataFrame): Datos de proyectos ya ajustados.
    
    Retorna:
    - pd.DataFrame: Tabla de importes mensuales devengados.
    """
    registros = []
    for _, row in tqdm(df.iterrows(), total=df.shape[0], desc="Procesando proyectos"):
        if pd.isnull(row['fecha_inicio']) or pd.isnull(row['fecha_fin']):
            continue
        
        fecha_actual        = row['fecha_inicio']
        fecha_fin           = row['fecha_fin']
        meses_diferencia    = (fecha_fin.year - fecha_actual.year) * 12 + (fecha_fin.month - fecha_actual.month) + 1
        
        if meses_diferencia <= 0:
            continue  # Evita divisiones por cero o negativas
        
        importe_mensual = row['importe_gestion'] / meses_diferencia
        
        # Validaciones de campos vacíos
        gestor   = str(row['gestor']).strip() if pd.notnull(row['gestor']) else ""
        region   = str(row['region']).strip() if pd.notnull(row['region']) else ""

        if not gestor:
            gestor = "Sin gestor asignado"
        if not region:
            region = "Sin región asignada"

        valores_verdaderos = {'VERDADERO', 'TRUE', '1'} 
        
        for mes in range(meses_diferencia):
            registros.append({
                "Tipo_Contenido":       "Mes gestionado",
                "Tipo_Registro":        "Mes Importe gestionado",
                "Creado por":           "Proceso python",
                "id CRM":               row['id_crm'],
                "Región":               region,
                "Gestor":               gestor,
                "Programa":             row['programa'],
                "Num Mes por Devengar": f"{mes + 1}/{meses_diferencia}",
                "Mes Devengado":        (fecha_actual + relativedelta(months=mes)).strftime('%Y-%m-%d'),
                "Importe Devengado Mes": round(importe_mensual, 2),
                "Suma el Importe":      1 if str(row.get('importe_por_gestionar', '')).strip().upper() in valores_verdaderos else 0
                #"Suma el Importe": 1 if str(row.get('importe_por_gestionar_py', '')).strip().upper() == 1 else 0
                #"Suma el Importe": row['importe_por_gestionar_py']
            })
    return pd.DataFrame(registros)


def generar_importes_gestionado2(df):
    """
    Calcula los importes mensuales devengados por proyecto.
    
    Por cada mes dentro del rango de un proyecto, genera una fila con el importe correspondiente.
    
    Parámetros:
    - df (pd.DataFrame): Datos de proyectos ya ajustados.
    
    Retorna:
    - pd.DataFrame: Tabla de importes mensuales devengados.
    """
    registros = []
    for _, row in tqdm(df.iterrows(), total=df.shape[0], desc="Procesando proyectos"):
        if pd.isnull(row['fecha_inicio']) or pd.isnull(row['fecha_fin']):
            continue
        
        fecha_actual        = row['fecha_inicio']
        fecha_fin           = row['fecha_fin']
        meses_diferencia    = (fecha_fin.year - fecha_actual.year) * 12 + (fecha_fin.month - fecha_actual.month) + 1
        
        if meses_diferencia <= 0:
            continue  # Evita divisiones por cero o negativas
        
        importe_mensual = row['importe_gestion'] / meses_diferencia
        
        # Validaciones de campos vacíos
        gestor   = str(row['gestor']).strip() if pd.notnull(row['gestor']) else ""
        region   = str(row['region']).strip() if pd.notnull(row['region']) else ""

        if not gestor:
            gestor = "Sin gestor asignado"
        if not region:
            region = "Sin región asignada"

        # Obtener el valor original del campo
        valor_original = row.get('importe_por_gestionar', '')

        # Depuración
        #print(f"[DEBUG] id_crm: {row.get('id_crm')} | Valor original: {valor_original} ({type(valor_original)})")

        # Evaluar si se debe sumar el importe
        incluir_importe = 1 if es_verdadero(valor_original) else 0

        for mes in range(meses_diferencia):
            registros.append({
                "Tipo_Contenido":       "Mes gestionado",
                "Tipo_Registro":        "Mes Importe gestionado",
                "Creado por":           "Proceso python",
                "id CRM":               row['id_crm'],
                "Región":               region,
                "Gestor":               gestor,
                "Programa":             row['programa'],
                "Num Mes por Devengar": f"{mes + 1}/{meses_diferencia}",
                "Mes Devengado":        (fecha_actual + relativedelta(months=mes)).strftime('%Y-%m-%d'),
                "Importe Devengado Mes": round(importe_mensual, 2),
                "Suma el Importe":      incluir_importe
            })
    return pd.DataFrame(registros)


#def exportar_a_excel(df, nombre_archivo="Importes_GestionadoOrigen2.xlsx"):
    """
    Exporta los datos a un archivo Excel.
    
    Parámetros:
    - df (pd.DataFrame): Datos a exportar.
    - nombre_archivo (str): Nombre del archivo de salida.
    """
#    df.to_excel(nombre_archivo, index=False)
#    print(f"Archivo {nombre_archivo} generado exitosamente.")

def exportar_a_excel(df, nombre_archivo="modeloDatos1.xlsx"):
    """
    Exporta los datos a la carpeta output/ relativa al script.
    Opcionalmente intenta también copiar a la ruta de OneDrive si existe.

    Parámetros:
    - df (pd.DataFrame): Datos a exportar.
    - nombre_archivo (str): Nombre del archivo de salida (por defecto 'modeloDatos1.xlsx').
    """
    # 1) Archivo en output/ (relativo al script)
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    carpeta_output = os.path.join(directorio_actual, "output")
    os.makedirs(carpeta_output, exist_ok=True)
    ruta_output = os.path.join(carpeta_output, nombre_archivo)
    df.to_excel(ruta_output, index=False)
    print(f"Archivo {nombre_archivo} generado exitosamente en: {ruta_output}")

    # 2) Copia opcional en la ruta de OneDrive (si existe en este equipo)
    segunda_ruta = r"C:\Users\L03523797\OneDrive - Instituto Tecnologico y de Estudios Superiores de Monterrey\Estrategia de Datos VPAF's files - Proyect Hub"

    try:
        os.makedirs(segunda_ruta, exist_ok=True)
    except Exception as e:
        print(f"⚠️ No se pudo crear/verificar la carpeta de destino OneDrive: {e}")

    ruta_completa_segunda = os.path.join(segunda_ruta, nombre_archivo)
    try:
        df.to_excel(ruta_completa_segunda, index=False)
        print(f"Copia adicional generada en: {ruta_completa_segunda}")
    except Exception as e:
        print(f"⚠️ No se pudo guardar la copia en OneDrive (no crítico): {e}")    

def insertar_chunk_borrado(chunk):
    
    thread_name = threading.current_thread().name
    total_registros = len(chunk)
    next_log_percent = 10  # empieza con 10%
    print(f"🧵 {thread_name} iniciado → insertará {total_registros} registros")
    
    conn = crear_conexion_sql('Edata_Qlik')
    cursor = conn.cursor()

    insert_query = """
        INSERT INTO dbo.ETL_Extraer_Importe_Gestionado (
            id_crm, 
            region, 
            gestor, 
            programa,
            num_mes_gestionar, 
            fecha_gestionar,
            importe_gestionar, 
            aplica_importe_gestion,
            usuario_actualizo, 
            fecha_actualizo
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    errores = 0
    errores_lista = []

    for i, (_, row) in enumerate(chunk.iterrows(), start=1):
        try:
            valores = (
                str(row['id CRM']),
                str(row['Región']),
                str(row['Gestor']),
                str(row['Programa']),
                str(row['Num Mes por Devengar']),  # ← ya es texto con formato "1/4"
                row['Mes Devengado'].date() if pd.notnull(row['Mes Devengado']) else None,
                float(row['Importe Devengado Mes']) if pd.notnull(row['Importe Devengado Mes']) else 0.0,
                int(row['Suma el Importe']) if pd.notnull(row['Suma el Importe']) else 0,
                str(row['Creado por']),
                datetime.now().date()
            )
            cursor.execute(insert_query, valores)
        except Exception as e:
            errores += 1
            row_dict = row.to_dict()
            row_dict["Error"] = str(e)
            errores_lista.append(row_dict)
            
        # Mensaje de avance cada 10%
        porcentaje_actual = int((i / total_registros) * 100)
        if porcentaje_actual >= next_log_percent:
            print(f"🔁 {thread_name} → {porcentaje_actual}% completado ({i}/{total_registros})")
            next_log_percent += 10
    
    conn.commit()
    conn.close()
    return errores, errores_lista


def insertar_datos_en_sql_multihilo_borrado(df, num_hilos=None):
    """
    Borra todos los registros de la tabla y luego inserta los nuevos usando hilos.
    El número de hilos se adapta automáticamente a la capacidad del equipo.
    """

    # 🔢 Determinar número de hilos según el equipo
    if num_hilos is None:
        cpu_hilos = os.cpu_count() or 4
        num_hilos = min(cpu_hilos, 16)  # Máximo 8 hilos para no saturar
        print(f"🧠 Núcleos detectados: {os.cpu_count()}")
    
    # Limpieza de tipos
    df['Mes Devengado']         = pd.to_datetime(df['Mes Devengado'], errors='coerce')
    df['Importe Devengado Mes'] = pd.to_numeric(df['Importe Devengado Mes'], errors='coerce')
    df['Suma el Importe']       = pd.to_numeric(df['Suma el Importe'], errors='coerce')


    # Paso 1: Borrar registros existentes
    conn = crear_conexion_sql('Edata_Qlik')
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM dbo.ETL_Extraer_Importe_Gestionado")
        conn.commit()
        print("🧹 Todos los registros existentes fueron eliminados.")
    except Exception as e:
        print(f"❌ Error al eliminar registros: {e}")
        conn.rollback()
        conn.close()
        return
    conn.close()

    # Paso 2: Procesamiento por chunks
    #chunks = np.array_split(df, num_hilos)
    index_chunks = np.array_split(df.index.to_numpy(), num_hilos)
    chunks = [df.loc[idx].copy() for idx in index_chunks if len(idx) > 0]
    errores_total = 0
    errores_lista = []

    print(f"🚀 Insertando {df.shape[0]} registros usando {num_hilos} hilos...")

    with ThreadPoolExecutor(max_workers=num_hilos) as executor:
        futures = [executor.submit(insertar_chunk_borrado, chunk) for chunk in chunks]
        for future in futures:
            errores_chunk, lista_errores_chunk = future.result()
            errores_total += errores_chunk
            errores_lista.extend(lista_errores_chunk)

    # Paso 3: Reporte
    print("\n📊 Resumen de inserción:")
    print(f"✔️  Registros insertados: {df.shape[0] - errores_total}")
    print(f"❌ Errores: {errores_total}")
    if errores_lista:
        pd.DataFrame(errores_lista).to_excel("errores_insercion_borrado.xlsx", index=False)
        print("📁 Se guardó un archivo con los errores: errores_insercion_borrado.xlsx")


def main():
    """
    Flujo principal del proceso:
    1. Obtiene los datos desde Excel o SQL.
    2. Ajusta las fechas de los proyectos.
    3. Calcula los importes devengados por mes.
    4. Exporta los resultados a un archivo Excel.
    5. Elimina los registros actuales en la base de datos y luego inserta los nuevos.
    """
    
    # Puedes cambiar este valor a 'sql' si prefieres traer los datos desde la BD
    origen = 'excel'
    
    # Paso 1: Obtener los datos
    df = obtener_datos(origen)
    
    # Paso 2: Ajustar las fechas
    df = ajustar_fechas(df)
    
    # Paso 3: Generar importes devengados por mes
    #datos_devengados = generar_importes_gestionado(df)
    datos_devengados = generar_importes_gestionado2(df)
    
    # Paso 4: Exportar a Excel como respaldo
    exportar_a_excel(datos_devengados)
    
    # Paso 5: Insertar en la base de datos después de eliminar los datos actuales
    #insertar_datos_en_sql_borrado_previo(datos_devengados)
    insertar_datos_en_sql_multihilo_borrado(datos_devengados)

if __name__ == "__main__":
    main()
