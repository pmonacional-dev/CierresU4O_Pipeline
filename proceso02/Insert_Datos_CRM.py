import pyodbc
import re 
import sys
import pandas as pd
import numpy as np
import math

sys.path.append("Campus.py")
from Conexion_SQL           import crear_conexion_sql
from Conexion_SalesForce    import connect_to_salesforce
from sqlalchemy             import create_engine
from Campus                 import *
from datetime               import datetime

def extraer_nivel(texto):
    """
    Extrae el nivel de impacto (Nivel 1-4) desde el texto de capacidad de acción.

    Parámetros:
        texto (str): Texto desde el cual se extrae el nivel.

    Retorna:
        str: Nivel encontrado (ej. "Nivel 3") o "Sin información en CRM".
    """
    
    if not isinstance(texto, str):
        return "Sin información en CRM"

    match = re.search(r"Nivel\s[1-4]", texto)
    return match.group() if match else "Sin información en CRM"

def obtener_datos(cursor):
    """
    Obtiene los registros (id_crm) de la tabla Envios_cerradas_ganadas que tienen estatus_envio = 0
    y realiza una consulta a Salesforce para obtener la información necesaria, incluyendo las nuevas columnas.
    """

    # Ejecutamos la consulta a SQL Server para obtener los IDs de CRM pendientes.
    cursor.execute("""
        SELECT id_crm
        FROM Envios_cerradas_ganadas
        WHERE estatus_envio = 0
    """)

    registros = cursor.fetchall()
    # Obtener los ID de CRM
    id_crm_list = [registro[0] for registro in registros]

    # Convertir los ID de CRM en una cadena separada por comas y comillas simples para la consulta SOQL
    id_crm_str = ','.join([f"'{id_crm}'" for id_crm in id_crm_list])

    # Validar que haya al menos un ID
    if not id_crm_str:
        print("La cadena de IDs de CRM está vacía. El programa se detendrá.")
        #sys.exit()
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame()
        )

    # Construir la consulta SOQL, incluyendo las columnas nuevas
    soql_query = f"""
        SELECT 
            Id,
            OwnerId,
            VEC_Coordinador_academico1__c,
            VEC_Desarrollador_de_solucion__c,
            AccountId,
            VEC_BusinessContact__c,
            Name,
            VEC_Problems__c,
            VEC_Capacidad_de_accion_Postventa__c,
            VEC_Descripcion_del_impacto_Postventa__c,
            VEC_Definicion_de_la_necesidad_Postventa__c,
            VEC_Resultado_esperado_Postventa__c,
            Amount,
            CloseDate,
            VEC_Zona_Regional__c,
            VEC_Zona_de_impacto__c,
            VEC_Campus_ejecucion__c,
            VEC_Escuelas_que_participan__c,
            VEC_ProgramType__c,
            VEC_EjecutionStart__c,
            VEC_FinishedExecution__c,
            VEC_Es_factible_el_seguimiento_Postventa__c,
            VEC_Impacto_medida_economica_Postventa__c,
            VEC_Frecuencia_de_medicion_Postventa__c,
            VEC_Instrumento_de_medicion_Postventa__c,
            VEC_Indicador_Postventa__c,
            VEC_Fecha_de_seguimiento_Postventa__c,
            VEC_Horas_totales_de_imparticion__c,
            VEC_Numero_de_grupos__c,
            VEC_Numero_de_participantes_por_grupo__c,
            VEC_Numero_de_modulos__c,
            VEC_Modalidad_1__c,
            VEC_Modalidad_2__c,
            VEC_Area_tematica__c,
            VEC_Tipo_Iniciativa__c,
            VEC_CeCo__c,
            VEC_Codigo_de_Servicio_del__c,
            Description,
            CurrencyIsoCode,
            StageName,
            VEC_Fecha_encuesta_final_cliente__c,
            VEC_PlaceCourse__c,
            VEC_Medio_sesiones_sincronas__c,
            VEC_AcademicLevel__c,
            VEC_Nivel_organizacional__c,
            VEC_Nombre_de_Programa_en_diploma__c,
            VEC_OppOrigin__c,
            VEC_Participacion__c,
            VEC_Plataforma_de_aprendizaje_de_EC__c,
            Probability,
            VEC_Ubicacion_territorial_de_la_empresa__c,
            VEC_Folio_reflexiona__c,
            VEC_Horas_totales_imparticion_participa__c
        FROM Opportunity
        WHERE Id IN ({id_crm_str})
    """

    # Conectarse a Salesforce y ejecutar la consulta
    sf = connect_to_salesforce()
    result = sf.query_all(soql_query)
    opportunity_records = result["records"]

    # Crear un DataFrame con los registros de Salesforce
    df_opportunity = pd.DataFrame(opportunity_records)

    # Concatenar VEC_Modalidad_1__c y VEC_Modalidad_2__c si son diferentes
    for i in range(len(df_opportunity)):
        if (
            "VEC_Modalidad_1__c" in df_opportunity.columns
            and "VEC_Modalidad_2__c" in df_opportunity.columns
            and df_opportunity.loc[i, "VEC_Modalidad_1__c"] != df_opportunity.loc[i, "VEC_Modalidad_2__c"]
            and df_opportunity.loc[i, "VEC_Modalidad_2__c"] not in [None, ""]
        ):
            df_opportunity.loc[i, "VEC_Modalidad_1__c"] = (
                str(df_opportunity.loc[i, "VEC_Modalidad_1__c"]) + " - " + str(df_opportunity.loc[i, "VEC_Modalidad_2__c"])
            )

    # Renombrar columnas a nombres más adecuados para la base de datos local
    df_opportunity.rename(
        columns={
            "Id":                                           "id_crm",
            "OwnerId":                                      "id_asesor",
            "VEC_Coordinador_academico1__c":                "id_coordinador",
            "VEC_Desarrollador_de_solucion__c":             "id_diseñador",
            "AccountId":                                    "id_cliente",
            "VEC_BusinessContact__c":                       "id_contacto",
            "Name":                                         "nombre_programa",
            "VEC_Problems__c":                              "objetivo_programa",
            "VEC_Capacidad_de_accion_Postventa__c":         "capacidad_accion",
            "VEC_Descripcion_del_impacto_Postventa__c":     "descripcion_impacto",
            "VEC_Definicion_de_la_necesidad_Postventa__c":  "definicion_necesidad",
            "VEC_Resultado_esperado_Postventa__c":          "resultado_esperado",
            "Amount":                                       "importe_venta",
            "CloseDate":                                    "fecha_cierre_ganada",
            "VEC_Zona_Regional__c":                         "region",
            "VEC_Zona_de_impacto__c":                       "region_impacto",
            "VEC_Campus_ejecucion__c":                      "campus",
            "VEC_Escuelas_que_participan__c":               "escuela",
            "VEC_ProgramType__c":                           "tipo_programa",
            "VEC_EjecutionStart__c":                        "fecha_inicio",
            "VEC_FinishedExecution__c":                     "fecha_fin",
            "VEC_Es_factible_el_seguimiento_Postventa__c":  "factibilidad_seguimiento",
            "VEC_Impacto_medida_economica_Postventa__c":    "medida_impacto_economico",
            "VEC_Frecuencia_de_medicion_Postventa__c":      "frecuencia_medicion",
            "VEC_Instrumento_de_medicion_Postventa__c":     "instrumento_medicion",
            "VEC_Indicador_Postventa__c":                   "indicador_postventa",
            "VEC_Fecha_de_seguimiento_Postventa__c":        "fecha_seguimiento",
            "VEC_Horas_totales_de_imparticion__c":          "duración_hrs",
            "VEC_Numero_de_grupos__c":                      "no_grupos",
            "VEC_Numero_de_participantes_por_grupo__c":     "no_participantes",
            "VEC_Numero_de_modulos__c":                     "no_modulos",
            "VEC_Modalidad_1__c":                           "modalidad",
            "VEC_Area_tematica__c":                         "area_tematica",
            "VEC_Tipo_Iniciativa__c":                       "tipo_iniciativa",
            "VEC_CeCo__c":                                  "orden_interna",
            "VEC_Codigo_de_Servicio_del__c":                "codigo_servicio",
            "Description":                                  "descripcion_proyecto",
            "CurrencyIsoCode":                              "divisa",
            "StageName":                                    "etapa_oportunidad",
            "VEC_Fecha_encuesta_final_cliente__c":          "fecha_encuesta_final",
            "VEC_PlaceCourse__c":                           "lugar_imparticion",
            "VEC_Medio_sesiones_sincronas__c":              "medio_sesiones_asincronas",
            "VEC_AcademicLevel__c":                         "nivel_academico_participantes",
            "VEC_Nivel_organizacional__c":                  "nivel_organizacional",
            "VEC_Nombre_de_Programa_en_diploma__c":         "nombre_programa_en_diploma",
            "VEC_OppOrigin__c":                             "origen_oportunidad",
            "VEC_Participacion__c":                         "participacion",
            "VEC_Plataforma_de_aprendizaje_de_EC__c":       "plataforma_aprendizaje",
            "Probability":                                  "probabilidad",
            "VEC_Ubicacion_territorial_de_la_empresa__c":   "ubicacion_territorial_empresa",
            "VEC_Folio_reflexiona__c":                      "folio_reflexiona",
            "VEC_Horas_totales_imparticion_participa__c":   "duracion_participantes_hrs"
        },
        inplace=True
    )

    df_opportunity["nivel_impacto"] = df_opportunity["capacidad_accion"].apply(extraer_nivel)

    # Eliminar la columna VEC_Modalidad_2__c (ya está concatenada en 'modalidad')
    if "VEC_Modalidad_2__c" in df_opportunity.columns:
        df_opportunity.drop(columns=["VEC_Modalidad_2__c"], inplace=True)

    # Rellenar valores nulos en columnas clave
    df_opportunity["id_coordinador"] = df_opportunity["id_coordinador"].fillna("0")
    df_opportunity["id_diseñador"] = df_opportunity["id_diseñador"].fillna("1")
    df_opportunity["orden_interna"] = df_opportunity["orden_interna"].fillna("Sin información en CRM")
    df_opportunity["codigo_servicio"] = df_opportunity["codigo_servicio"].fillna("Sin información en CRM")

    # df_opportunity debe tener la columna 'id_crm'
    df_opportunity["region"] = df_opportunity.apply(lambda row: asignar_region(cursor, row["id_crm"]), axis=1)

    # Agregar columnas auxiliares
    df_opportunity["link_crm"] = (
        "https://micrmtec.lightning.force.com/lightning/r/Opportunity/" 
        + df_opportunity["id_crm"] 
        + "/view"
    )
    df_opportunity["usuario_actualiza"] = "Python"
    #df_opportunity["fecha_actualizacion"] = pd.to_datetime("now", utc=True)
    df_opportunity["fecha_actualizacion"] = datetime.now().replace(microsecond=0)

    """
    *** Apartado Contact ***
    """
    # Obtener los IDs de Contacto
    contact_ids = [
        record[field]
        for record in opportunity_records
        for field in ["VEC_BusinessContact__c", "VEC_Coordinador_academico1__c", "VEC_Desarrollador_de_solucion__c"]
        if field in record and record[field]
    ]

    contact_ids_str = ",".join([f"'{contact_id}'" for contact_id in contact_ids])
    sf_query_contact = f"""
        SELECT
            Id,
            Name,
            Email,
            Title
        FROM Contact
        WHERE Id IN ({contact_ids_str})
    """
    result_contact = sf.query_all(sf_query_contact)
    contact_records = result_contact["records"]
    df_contact = pd.DataFrame(contact_records).fillna("Sin información en CRM")
    df_contact.rename(columns={
        "Id":    "id_crm",
        "Name":  "nombre",
        "Email": "email",
        "Title": "puesto"
    }, inplace=True)

    """
    *** Apartado User ***
    """

    """
    owner_ids = [record["OwnerId"] for record in opportunity_records if "OwnerId" in record]
    owner_ids_str = ",".join([f"'{owner_id}'" for owner_id in owner_ids])
    sf_query_user = f"""
        #SELECT
        #    Id,
        #    Name,
        #    EmployeeNumber,
        #    Email,
        #    VEC_Campus_de_Usuario__c,
        #    VEC_Tipo_usuario__c,
        #    VEC_Zona_Regional__c 
        #FROM User
        #WHERE Id IN ({owner_ids_str})
    """
    result_user = sf.query_all(sf_query_user)
    user_records = result_user["records"]
    df_user = pd.DataFrame(user_records).fillna("Sin información en CRM")
    df_user.rename(columns={
        "Id":                  "id_crm",
        "Name":                "nombre",
        "EmployeeNumber":      "No_Empleado",
        "Email":               "email",
        "VEC_Campus_de_Usuario__c": "campus",
        "VEC_Tipo_usuario__c": "tipo_usuario",
        "VEC_Zona_Regional__c": "zona_regional"
    }, inplace=True)
    """
    owner_ids = [record["OwnerId"] for record in opportunity_records if "OwnerId" in record and record["OwnerId"]]
    owner_ids = list(set(owner_ids))  # quitar duplicados

    if owner_ids:
        owner_ids_str = ",".join([f"'{owner_id}'" for owner_id in owner_ids])
        sf_query_user = f"""
            SELECT
                Id,
                Name,
                EmployeeNumber,
                Email,
                VEC_Tipo_usuario__c
            FROM User
            WHERE Id IN ({owner_ids_str})
        """
        result_user = sf.query_all(sf_query_user)
        user_records = result_user["records"]
        df_user = pd.DataFrame(user_records).fillna("Sin información en CRM")

        df_user.rename(columns={
            "Id":                  "id_crm",
            "Name":                "nombre",
            "EmployeeNumber":      "No_Empleado",
            "Email":               "email",
            "VEC_Tipo_usuario__c": "tipo_usuario"
        }, inplace=True)

    else:
        df_user = pd.DataFrame(columns=[
            "id_crm", "nombre", "No_Empleado", "email", "tipo_usuario"
        ])

    """
    *** Apartado Account ***
    """
    account_ids = [record["AccountId"] for record in opportunity_records if "AccountId" in record]
    account_ids_str = ",".join([f"'{account_id}'" for account_id in account_ids])
    sf_query_account = f"""
        SELECT
            Id,
            Name,
            Phone,
            Website
        FROM Account
        WHERE Id IN ({account_ids_str})
    """
    result_account = sf.query_all(sf_query_account)
    account_records = result_account["records"]
    df_account = pd.DataFrame(account_records).fillna("Sin información en CRM")
    df_account.rename(columns={
        "Id":     "id_crm",
        "Name":   "nombre",
        "Phone":  "telefono",
        "Website": "web_site"
    }, inplace=True)

    # Cerrar la sesión de Salesforce
    sf.session.close()

    return df_opportunity, df_contact, df_user, df_account


def insertar_datos_Datos_CRM(df, cursor):
    """
    EJEMPLO DE FUNCIÓN QUE PODRÍA INSERTAR O VERIFICAR REGISTROS EN LA TABLA 'Datos_CRM'.
    (No se modifica a menos que necesites guardar nuevas columnas en esa tabla)
    """
    for index, row in df.iterrows():
        try:
            cursor.execute("""
                SELECT * 
                FROM Datos_CRM
                WHERE id_crm = ? 
            """, row['Id'])

            if cursor.fetchone() is None:
                cursor.execute("""
                    INSERT INTO Datos_CRM (
                        id_crm, 
                        fecha_cerrada_ganada, 
                        estatus_envio
                    )
                    VALUES (?, ?, ?)
                """, row['Id'], row['fecha_cierre_CRM'], 0)
                
                print("Registro insertado exitosamente:", row['id_oportunidad_CRM'], row['fecha_cierre_CRM'])
            else:
                print("El registro ya existe, no se hace nada:", row['id_oportunidad_CRM'], row['fecha_cierre_CRM'])

        except pyodbc.Error as e:
            print(f"Error al insertar fila: {e}")


def insert_into_sql(df, opcion, conexion):

    table_map = {1: "Account_CRM", 2: "Contact_CRM", 3: "User_CRM", 4: "Datos_CRM"}
    table_name = table_map.get(opcion)
    if not table_name:
        return

    # 1) Limpieza inicial
    if "attributes" in df.columns:
        df = df.drop(columns=["attributes"])

    # 2) Leer tipos de columnas desde SQL Server (para rangos correctos de fechas)
    #    (Usa schema dbo por default; si tu tabla está en otro schema, ajusta TABLE_SCHEMA.)
    col_types = {}  # {col_name: data_type}
    type_cur = conexion.cursor()
    try:
        type_cur.execute("""
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = ? AND TABLE_SCHEMA = 'dbo'
        """, (table_name,))
        for col_name, data_type in type_cur.fetchall():
            col_types[col_name] = str(data_type).lower()
    except Exception as e:
        print(f"⚠️ No pude leer tipos de columnas de {table_name} (seguiré sin esquema): {e}")
    finally:
        try:
            type_cur.close()
        except:
            pass

    # Rangos por tipo SQL (los más problemáticos son smalldatetime)
    ranges = {
        "smalldatetime": (pd.Timestamp("1900-01-01"), pd.Timestamp("2079-06-06 23:59:59")),
        "datetime":      (pd.Timestamp("1753-01-01"), pd.Timestamp("9999-12-31 23:59:59")),
        "datetime2":     (pd.Timestamp("0001-01-01"), pd.Timestamp("9999-12-31 23:59:59")),
        "date":          (pd.Timestamp("0001-01-01"), pd.Timestamp("9999-12-31")),
    }

    # Helper: decide si una columna debe tratarse como fecha
    def is_date_col(col):
        c = col.lower()
        if "fecha" in c or "date" in c:
            return True
        # si el schema dice que es tipo fecha, también
        t = col_types.get(col, "")
        if t in ("date", "datetime", "datetime2", "smalldatetime"):
            return True
        # si ya viene como datetime en pandas
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return True
        return False

    # 3) PROCESAMIENTO DE FECHAS con rango según tipo SQL (si se conoce)
    for col in df.columns:
        if not is_date_col(col):
            continue

        # Convertir a datetime (si venía como string, aquí lo intentamos)
        s = pd.to_datetime(df[col], errors="coerce")

        # Quitar tz si existiera
        try:
            if getattr(s.dt, "tz", None) is not None:
                s = s.dt.tz_localize(None)
        except Exception:
            pass

        # Determinar rango permitido para ESA columna
        sql_t = col_types.get(col, "")
        min_dt, max_dt = ranges.get(sql_t, (pd.Timestamp("1753-01-01"), pd.Timestamp("9999-12-31 23:59:59")))

        # Convertir a python datetime sin microsegundos y fuera de rango -> None
        def _to_py_dt(x):
            if pd.isna(x):
                return None
            if x < min_dt or x > max_dt:
                return None
            return x.to_pydatetime().replace(microsecond=0)

        df[col] = s.apply(_to_py_dt)

    # 4) Normalizar nulos (primer paso)
    df = df.where(pd.notnull(df), None)

    # 5) Verificar existentes
    cur = conexion.cursor()
    existentes = set()
    try:
        cur.execute(f"SELECT id_crm FROM {table_name}")
        for (id_crm,) in cur.fetchall():
            existentes.add(str(id_crm))
    except Exception as e:
        print(f"Error leyendo existentes: {e}")

    if "id_crm" not in df.columns:
        raise KeyError("La columna 'id_crm' no existe en el DataFrame.")

    df_nuevos = df[~df["id_crm"].astype(str).isin(existentes)].copy()

    if df_nuevos.empty:
        print(f"No hay registros nuevos para {table_name}.")
        try:
            cur.close()
        except:
            pass
        return

    # 6) Preparar INSERT
    cols = list(df_nuevos.columns)
    col_list = ", ".join(f"[{c}]" for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    sql_insert = f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})"

    # 7) CORRECCIÓN CLAVE: evitar NaN/Inf en floats (SQL float no acepta NaN/Inf)
    df_nuevos = df_nuevos.astype(object)
    df_nuevos = df_nuevos.replace({np.nan: None, np.inf: None, -np.inf: None})
    data = [tuple(x) for x in df_nuevos.to_numpy(dtype=object)]

    # 8) Intentar inserción masiva + modo detective si falla
    try:
        cur.fast_executemany = True
        cur.executemany(sql_insert, data)

        # Si tu conexión NO está en autocommit, descomenta:
        # conexion.commit()

        print(f"Se han insertado {len(data)} registros en {table_name}.\n")

    except pyodbc.Error as e:
        print(f"⚠️ Error masivo en {table_name}. Iniciando modo detective...")
        print(f"Mensaje SQL (masivo): {e}")

        # Cursor nuevo para debug fila por fila
        debug_cur = conexion.cursor()

        def _flag_nan_inf(v):
            if isinstance(v, float):
                if math.isnan(v):
                    return " <-- NaN"
                if math.isinf(v):
                    return " <-- INF"
            return ""

        for i, fila in enumerate(data):
            try:
                debug_cur.execute(sql_insert, fila)
            except Exception as row_e:
                print(f"\n❌ ERROR ENCONTRADO EN LA FILA {i+1}:")
                print(f"Mensaje SQL: {row_e}")
                print("-" * 50)
                print("ANÁLISIS DE DATOS VS COLUMNAS (con índice de parámetro):")

                for idx, (nombre_col, valor) in enumerate(zip(cols, fila), start=1):
                    # marcar columnas tipo fecha y mostrar el tipo SQL si existe
                    sql_t = col_types.get(nombre_col, "")
                    extra = f" [sql:{sql_t}]" if sql_t else ""
                    print(
                        f"({idx}) [{nombre_col}]{extra}: {valor!r} ({type(valor).__name__}){_flag_nan_inf(valor)}"
                    )

                print("-" * 50)
                print("Pista: si el error dice 'Datetime field overflow', busca una fecha fuera de rango.")
                print("Si tu columna SQL es smalldatetime, solo acepta 1900-01-01 a 2079-06-06.")
                break

        try:
            debug_cur.close()
        except:
            pass

    finally:
        try:
            cur.close()
        except:
            pass

def insert_into_sql_old(df, opcion, conexion):
    """
    Inserta nuevos registros en la tabla correspondiente (Account_CRM, Contact_CRM, User_CRM, o Datos_CRM).
    """
    reg_insertados = 0
    engine = create_engine("mssql+pyodbc://", creator=lambda: conexion)

    if opcion == 1:
        table_name = 'Account_CRM'
    elif opcion == 2:
        table_name = 'Contact_CRM'
    elif opcion == 3:
        table_name = 'User_CRM'
    elif opcion == 4:
        table_name = 'Datos_CRM'
    else:
        print("Opción no válida.")
        return
    
    # Elimina la columna 'attributes' si existe
    if 'attributes' in df.columns:
        df = df.drop(columns='attributes')

    for i in df.index:
        row = df.loc[i]
        id_exists = pd.read_sql(
            f"SELECT 1 FROM {table_name} WHERE id_crm = '{row['id_crm']}'",
            engine
        )
        if id_exists.empty:
            row_df = pd.DataFrame(row).transpose()
            row_df.to_sql(table_name, engine, if_exists='append', index=False)
            print(f'Se ha insertado 1 registro en la tabla {table_name}.')
            reg_insertados += 1
        else:
            print(f'El registro con id_crm {row["id_crm"]} ya existe en la tabla {table_name}.')

    print(f'Se han insertado {reg_insertados} registros en la tabla {table_name}.\n')


def asignar_region(cursor, id_oportunidad_crm):
    """
    Obtiene la región asociada a una oportunidad desde la tabla Portafolio_PMO,
    buscando por el campo id_oportunidad_CRM.

    Parámetros:
        cursor (pyodbc.Cursor): Cursor activo de la conexión SQL.
        id_oportunidad_crm (str): ID de la oportunidad (id_crm en Salesforce).

    Retorna:
        str or None: Valor de la columna 'region_CRM' si se encuentra, None si no.
    """
    try:
        cursor.execute("""
            SELECT region_CRM 
            FROM Portafolio_PMO 
            WHERE id_oportunidad_CRM = ?
        """, id_oportunidad_crm)
        resultado = cursor.fetchone()
        return resultado[0] if resultado else None
    except pyodbc.Error as e:
        print(f"Error al buscar región para {id_oportunidad_crm}: {e}")
        return None


def main():
    """
    Flujo principal:
      1. Conectarse a SQL Server y obtener IDs de Envios_cerradas_ganadas.
      2. Consultar los datos en Salesforce, incluyendo columnas nuevas.
      3. Insertar registros en tablas locales (Account_CRM, Contact_CRM, User_CRM, Datos_CRM).
    """
    conn = crear_conexion_sql('BD_PMO')
    cursor = conn.cursor()

    try:
        # Obtener DataFrames principales desde SF
        registros_opportunity, registros_contact, registros_user, registros_account = obtener_datos(cursor)

        if registros_opportunity.empty:
            print("No hay oportunidades pendientes para Insert_Datos_CRM. Se regresa al flujo principal.")
            return

        # Insertar en tablas locales
        insert_into_sql(registros_account, 1, conn)
        insert_into_sql(registros_contact, 2, conn)
        insert_into_sql(registros_user, 3, conn)
        insert_into_sql(registros_opportunity, 4, conn)

        conn.commit()

    finally:
        cursor.close()
        conn.close()

    try:
        # Intentamos usar el cursor después de cerrarlo -> error esperado
        cursor.execute("SELECT 1")
    except pyodbc.ProgrammingError as e:
        print(f"La conexión se cerró correctamente: {e}")
    else:
        print("La conexión aún está abierta.")

if __name__ == "__main__":
    main()
