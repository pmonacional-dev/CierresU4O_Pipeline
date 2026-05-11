# -*- coding: utf-8 -*-
"""
Script nocturno para actualizar Datos_CRM con información de SalesforceTablero_Historico
y registrar los cambios en CRM_Actualizaciones_Log.

BD destino (update + log): BD_PMO
BD origen (datos más recientes): Edata_Qlik
"""

from datetime import datetime
from Conexion_SQL import crear_conexion_sql  # <-- usamos tu función
from datetime import datetime, date
import os
import pyodbc  # Solo para el type, si ya lo usas en Conexion_SQL

MODO_PRUEBA = False  # True, Cambia a False cuando ya quieras que actualice de verdad
USUARIO_PROCESO = 'script_python_cierre'

# Rutas base relativas al script
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGS_DIR = os.path.join(_BASE_DIR, "logs")

def guardar_cambios_modo_prueba(updates, logs, ruta_base="CRM_Actualizaciones_ModoPrueba"):
    """
    Genera un archivo .txt con TODO lo que se habría actualizado:
    - Usa la lista 'logs' (una entrada por campo actualizado).
    - También puede incluir un resumen por id_crm usando 'updates'.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_archivo = f"{ruta_base}_{timestamp}.txt"

    # Asegurar que exista la carpeta 'logs'
    carpeta_log = _LOGS_DIR
    os.makedirs(carpeta_log, exist_ok=True)

    ruta_completa = os.path.join(carpeta_log, nombre_archivo)

    with open(ruta_completa, "w", encoding="utf-8") as f:
        f.write("RESUMEN DE CAMBIOS (MODO PRUEBA - NO SE APLICARON A BD)\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"Total registros con cambios (updates): {len(updates)}\n")
        f.write(f"Total entradas de log (campo por campo): {len(logs)}\n\n")

        f.write("DETALLE POR CAMPO ACTUALIZADO (basado en CRM_Actualizaciones_Log):\n")
        f.write("-" * 80 + "\n")
        # logs: id_crm, campo_actualizado, valor_anterior, valor_nuevo
        for log in logs:
            f.write(
                f"id_crm: {log['id_crm']}\n"
                f"  campo: {log['campo_actualizado']}\n"
                f"  valor_anterior: {log['valor_anterior']}\n"
                f"  valor_nuevo   : {log['valor_nuevo']}\n"
                "------------------------------------------------------------\n"
            )

        f.write("\n\nRESUMEN POR REGISTRO (valores finales que se habrían dejado en Datos_CRM):\n")
        f.write("-" * 80 + "\n")
        # updates: id_crm, nombre_programa, importe_venta, fecha_cierre_ganada, escuela
        for u in updates:
            f.write(
                f"id_crm: {u['id_crm']}\n"
                f"  nombre_programa    : {u['nombre_programa']}\n"
                f"  importe_venta      : {u['importe_venta']}\n"
                f"  fecha_cierre_ganada: {u['fecha_cierre_ganada']}\n"
                f"  escuela            : {u['escuela']}\n"
                "============================================================\n"
            )

    print(f"[INFO] Archivo de modo prueba generado: {ruta_completa}")

# =====================================
# OBTENER DATOS UNIFICADOS (JOIN)
# =====================================
def obtener_datos_unificados(cursor):
    """
    Trae los valores de BD_PMO.dbo.Datos_CRM y Edata_Qlik.dbo.SalesforceTablero_Historico
    en una sola consulta, usando nombres de BD explícitos.

    IMPORTANTE:
    - Funciona si BD_PMO y Edata_Qlik están en el mismo servidor SQL.
    """

    query = """
    SELECT
        c.id_crm,
        c.nombre_programa      AS crm_nombre_programa,
        c.importe_venta        AS crm_importe_venta,
        c.fecha_cierre_ganada  AS crm_fecha_cierre_ganada,
        c.escuela              AS crm_escuela,

        s.LigaNombreOportunidad AS sf_nombre_programa,
        s.Importe               AS sf_importe_venta,
        s.FechaCierre           AS sf_fecha_cierre_ganada,
        s.Escuela               AS sf_escuela
    FROM BD_PMO.dbo.Datos_CRM c
    INNER JOIN Edata_Qlik.dbo.SalesforceTablero_Historico s
        ON c.id_crm = s.IdOportunidad
    """

    cursor.execute(query)
    columns = [col[0] for col in cursor.description]
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return records


# =====================================
# COMPARAR VALORES MANEJANDO NULLs
# =====================================
def son_diferentes(valor_crm, valor_sf):
    """Compara manejando NULLs/simplemente casteando ambos a string."""
    if valor_crm is None and valor_sf is None:
        return False
    return str(valor_crm) != str(valor_sf)


def formatear_valor_para_log(valor):
    """Convierte el valor a string para almacenarlo en NVARCHAR(4000)."""
    if valor is None:
        return None

    # Si es fecha o datetime → normalizamos a 'YYYY-MM-DD'
    if isinstance(valor, (datetime, date)):
        d = valor.date() if isinstance(valor, datetime) else valor
        return d.strftime("%Y-%m-%d")

    # Si es string, intentamos parsearla como fecha
    if isinstance(valor, str):
        d = parse_fecha(valor)
        if d is not None:
            return d.strftime("%Y-%m-%d")

    # Cualquier otro caso, lo regresamos como string
    return str(valor)


def parse_fecha(valor):
    """
    Intenta convertir 'valor' a date, soportando varios formatos.
    Devuelve:
      - date si se pudo parsear
      - None si no se pudo
    """
    if valor is None:
        return None

    # Si ya viene como datetime/date desde pyodbc:
    if isinstance(valor, (datetime, date)):
        return valor.date() if isinstance(valor, datetime) else valor

    # Si viene como string, intentamos varios formatos
    if isinstance(valor, str):
        texto = valor.strip()
        formatos = [
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%d/%m/%Y",
            "%d/%m/%Y %H:%M:%S",
        ]
        for fmt in formatos:
            try:
                return datetime.strptime(texto, fmt).date()
            except ValueError:
                continue

    # Si no se pudo interpretar como fecha:
    return None


def son_fechas_diferentes(f1, f2):
    """
    Compara dos valores que representan fechas.
    Considera iguales:
      - '2024-07-12' y '12/07/2024'
      - '2023-08-07 00:00:00' y '07/08/2023'
    """
    d1 = parse_fecha(f1)
    d2 = parse_fecha(f2)

    if d1 is None and d2 is None:
        return False  # ambos "vacíos"
    if d1 is None or d2 is None:
        return True   # uno tiene fecha, otro no
    return d1 != d2


# =====================================
# PROCESAR DIFERENCIAS: ARMAR UPDATES Y LOGS
# =====================================
def detectar_cambios(registros_unificados):
    """
    A partir de la lista de registros unificados (join),
    construye dos listas:
      - updates: info para actualizar Datos_CRM
      - logs: info para insertar en CRM_Actualizaciones_Log
    """
    updates = []  # cada elemento: {id_crm, nombre_programa, importe_venta, fecha_cierre_ganada, escuela}
    logs = []     # cada elemento: {id_crm, campo_actualizado, valor_anterior, valor_nuevo}

    for row in registros_unificados:
        id_crm = row['id_crm']

        # Valores actuales en BD_PMO
        crm_nombre_programa     = row['crm_nombre_programa']
        crm_importe_venta       = row['crm_importe_venta']
        crm_fecha_cierre_ganada = row['crm_fecha_cierre_ganada']
        crm_escuela             = row['crm_escuela']

        # Valores nuevos desde SF (Edata_Qlik)
        sf_nombre_programa     = row['sf_nombre_programa']
        sf_importe_venta       = row['sf_importe_venta']
        sf_fecha_cierre_ganada = row['sf_fecha_cierre_ganada']
        sf_escuela             = row['sf_escuela']

        hay_cambios = False

        # Registro base de update
        update_reg = {
            'id_crm': id_crm,
            'nombre_programa': crm_nombre_programa,
            'importe_venta': crm_importe_venta,
            'fecha_cierre_ganada': crm_fecha_cierre_ganada,
            'escuela': crm_escuela,
        }

        # 1) nombre_programa
        if son_diferentes(crm_nombre_programa, sf_nombre_programa):
            hay_cambios = True
            update_reg['nombre_programa'] = sf_nombre_programa
            logs.append({
                'id_crm': id_crm,
                'campo_actualizado': 'nombre_programa',
                'valor_anterior': formatear_valor_para_log(crm_nombre_programa),
                'valor_nuevo': formatear_valor_para_log(sf_nombre_programa),
            })

        # 2) importe_venta
        if son_diferentes(crm_importe_venta, sf_importe_venta):
            hay_cambios = True
            update_reg['importe_venta'] = sf_importe_venta
            logs.append({
                'id_crm': id_crm,
                'campo_actualizado': 'importe_venta',
                'valor_anterior': formatear_valor_para_log(crm_importe_venta),
                'valor_nuevo': formatear_valor_para_log(sf_importe_venta),
            })

        # 3) fecha_cierre_ganada (comparación especial de fechas)
        if son_fechas_diferentes(crm_fecha_cierre_ganada, sf_fecha_cierre_ganada):
            hay_cambios = True

            # Convertimos la fecha nueva a objeto date antes de mandarla al UPDATE
            nueva_fecha = parse_fecha(sf_fecha_cierre_ganada)

            # Si por alguna razón no se pudo parsear, mejor NO actualizamos la fecha
            # (así evitamos el error de conversión en SQL)
            if nueva_fecha is None:
                print(f"[WARN] No se pudo parsear FechaCierre para id_crm={id_crm}. "
                    f"Valor en SF: {sf_fecha_cierre_ganada}. Se omite la actualización de fecha.")
            else:
                update_reg['fecha_cierre_ganada'] = nueva_fecha
                logs.append({
                    'id_crm': id_crm,
                    'campo_actualizado': 'fecha_cierre_ganada',
                    'valor_anterior': formatear_valor_para_log(crm_fecha_cierre_ganada),
                    'valor_nuevo': formatear_valor_para_log(sf_fecha_cierre_ganada),
                })

        # 4) escuela
        if son_diferentes(crm_escuela, sf_escuela):
            hay_cambios = True
            update_reg['escuela'] = sf_escuela
            logs.append({
                'id_crm': id_crm,
                'campo_actualizado': 'escuela',
                'valor_anterior': formatear_valor_para_log(crm_escuela),
                'valor_nuevo': formatear_valor_para_log(sf_escuela),
            })

        if hay_cambios:
            updates.append(update_reg)

    return updates, logs


# =====================================
# APLICAR UPDATES E INSERTAR LOGS
# =====================================
def aplicar_cambios(conn, updates, logs):
    cursor = conn.cursor()

    # --- 1) Actualizar Datos_CRM
    update_sql = """
    UPDATE BD_PMO.dbo.Datos_CRM
    SET
        nombre_programa     = ?,
        importe_venta       = ?,
        fecha_cierre_ganada = ?,
        escuela             = ?
    WHERE id_crm = ?
    """

    update_params = [
        (
            u['nombre_programa'],
            u['importe_venta'],
            u['fecha_cierre_ganada'],
            u['escuela'],
            u['id_crm']
        )
        for u in updates
    ]

    if update_params:
        cursor.executemany(update_sql, update_params)
        print(f"[INFO] Updates en Datos_CRM ejecutados para {len(update_params)} registro(s).")

    # --- 2) Insertar en CRM_Actualizaciones_Log
    insert_sql = """
    INSERT INTO BD_PMO.dbo.CRM_Actualizaciones_Log (
        id_crm,
        campo_actualizado,
        valor_anterior,
        valor_nuevo,
        notificacion_enviada,
        usuario_proceso
    )
    VALUES (?, ?, ?, ?, 0, ?)
    """

    insert_params = [
        (
            log['id_crm'],
            log['campo_actualizado'],
            log['valor_anterior'],
            log['valor_nuevo'],
            USUARIO_PROCESO
        )
        for log in logs
    ]

    if insert_params:
        cursor.executemany(insert_sql, insert_params)
        print(f"[INFO] Inserts en CRM_Actualizaciones_Log ejecutados para {len(insert_params)} registro(s).")


# =====================================
# MAIN
# =====================================
def main():
    conn = None
    try:
        # Usamos tu función, apuntando a BD_PMO como BD por defecto
        conn = crear_conexion_sql('BD_PMO')

        # Por si tu función no lo configura, intentamos apagar autocommit
        try:
            conn.autocommit = False
        except Exception:
            pass

        cursor = conn.cursor()

        print("[INFO] Obteniendo datos unificados (Datos_CRM + SalesforceTablero_Historico)...")
        registros = obtener_datos_unificados(cursor)
        print(f"[INFO] Se obtuvieron {len(registros)} registro(s) para comparación.")

        print("[INFO] Detectando cambios...")
        updates, logs = detectar_cambios(registros)
        print(f"[INFO] Registros con cambios: {len(updates)}")
        print(f"[INFO] Entradas de log generadas: {len(logs)}")

        if not updates:
            print("[INFO] No hay cambios que aplicar. Fin del proceso.")
            conn.rollback()
            return

        print("[INFO] Aplicando cambios en base de datos...")

        if MODO_PRUEBA:
            print("[INFO] MODO PRUEBA ACTIVADO: NO se llamará a aplicar_cambios(), NO se hará COMMIT.")
            # Generar archivo TXT con TODO lo que se hubiera actualizado
            guardar_cambios_modo_prueba(updates, logs)

            print("[INFO] Haciendo ROLLBACK (no se guardó ningún cambio en BD).")
            conn.rollback()
        else:
               # Opcional: generar TXT también en modo real, solo como bitácora
            guardar_cambios_modo_prueba(updates, logs, ruta_base="CRM_Actualizaciones_Prod")
            
            aplicar_cambios(conn, updates, logs)
            conn.commit()
            print("[OK] Transacción confirmada (COMMIT). Proceso terminado correctamente.")


    except Exception as e:
        print("[ERROR] Ocurrió un error, haciendo ROLLBACK...")
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        print(f"[ERROR] Detalle: {e}")

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
