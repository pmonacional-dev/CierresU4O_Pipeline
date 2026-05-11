"""
================================================================================
U4O_Integrar_MapeoActividad.py
================================================================================

PROPÓSITO
---------
Integrar el universo de EMPRESAS U4O con sus métricas de venta, oportunidades
y señales de atención (Task/Event + EAC), para producir:

  1. CSV `ActividadRecompra_U4O.csv` — fila por EMPRESA con estatus de
     seguimiento, ventas históricas y atributos del asesor.
  2. Tabla `Reporte_AnalisisAtencionU4O` — fila por EMPRESA con el último
     contacto atendido, fuente de dato, fechas y diferencias temporales.

CONTEXTO EN EL PIPELINE
-----------------------
Este script se ejecuta DESPUÉS de:
  - U4O_Extraer_Actividades_DentroOportunidades.py  (Task/Event + Einstein por opp)
  - U4O_Extraer_Actividades_FueraOportunidades.py   (EAC + contactos sin opp,
                                                     incluyendo cuentas calientes)

Lee principalmente de:
  - Extraer_EmpresasU4O           (universo de empresas)
  - Extraer_OportunidadesU4O      (oportunidades y ventas)
  - Extraer_ActividadesU4O        (Task/Event)
  - Extraer_EinsteinCRM           (ActivityMetric / EAC)
  - Extraer_ContactosU4O          (puente contacto ↔ empresa)
  - Extraer_AsesoresU4O           (silo y jerarquía)
  - EmpresasHomologadas           (nombres canónicos para agrupar duplicados)
  - Salesforce_StatusKAM (SIN_Data) (zona y estatus del asesor)

CONCEPTOS CLAVE
---------------
- EMPRESA HOMOLOGADA: nombre canónico en `EmpresasHomologadas.NombrePrincipal`
  usado para identificar a una misma cuenta aunque existan múltiples registros
  con nombres distintos en CRM (ej. "Tupperware" vs "Tupperware SA de CV").
- ESTATUS DE SEGUIMIENTO: clasificación del estado comercial de la empresa,
  combinando actividad (Task/Event/EAC) con ventas ganadas en el año actual.
- PUENTE CONTACTO↔EMPRESA para EAC: tres vías — (a) Task/Event con AccountId,
  (b) EAC sobre `Contact.AccountId`, (c) EAC sobre `Opp.AccountId` cuando el
  contacto es `VEC_BusinessContact__c` (añadido para no perder señal cuando
  la cuenta del contacto difiere de la cuenta de la opp).

ESTRUCTURA DEL SCRIPT
---------------------
Sección 1  — Fechas globales (ventanas 6m / 1y / 2y)
Sección 2  — Consultas extractoras (ventas por periodo, opps, actividad)
Sección 3  — Construcción del DF principal (df3) por Industry
Sección 4  — Merges masivos vectorizados
Sección 5  — Cálculo de "Actividad" (categoría de recencia)
Sección 6  — Cálculo de "EstatusSeguimiento_Zona" (lógica compleja con ramas)
Sección 7  — Merge final de Campus y Zona
Sección 8  — Exportación a CSV
Sección 9  — INSERT a `Reporte_AnalisisAtencionU4O` (tabla a nivel contacto)

================================================================================
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import Conexiones
import os

# Configuración para evitar el FutureWarning de Pandas sobre downcasting silencioso
pd.set_option('future.no_silent_downcasting', True)


def main(origen):
    startTime = datetime.now()
    
    # Establecer conexión
    conn_sql_server, cursor = Conexiones.connect_ETL_local_sql(origen)
    cursor.fast_executemany = True
    
    print("Inicio de mapeo estratégico de atención a empresas (Optimizado)")
    
    try:
        # ================================================================
        # SECCIÓN 1 — Fechas globales
        # ================================================================
        # Se fijan ventanas temporales que usarán las consultas de ventas:
        #   - 6 meses  (180d) : Venta6Meses
        #   - 1 año    (365d) : VentaAñoActual
        #   - 2 años   (730d) : límite superior de VentaAñoActual_Menos1
        # `normalize()` elimina la hora para evitar comparaciones inconsistentes.
        current_date = pd.to_datetime(datetime.now()).normalize()
        six_months_prior = (current_date - timedelta(days=180)).date()
        previous_year_date = (current_date - timedelta(days=365)).date()
        previous_2year_date = (current_date - timedelta(days=730)).date()
        current_date_date = current_date.date()

        # ================================================================
        # SECCIÓN 2 — Consultas extractoras (a DataFrames)
        # ================================================================
        # Helper para leer SQL → DataFrame (con columnas correctas según cursor.description).
        def get_df_from_query(query_str):
            cursor.execute(query_str)
            result = cursor.fetchall()
            if cursor.description:
                cols = [desc[0] for desc in cursor.description]
                return pd.DataFrame.from_records(result, columns=cols)
            return pd.DataFrame()

        # -----------------------------------------------------------------
        # 2.1 Campus por asesor
        # -----------------------------------------------------------------
        # El Campus se infiere del campo `VEC_Campus_de_usuario_del__c` de la
        # oportunidad más reciente del asesor (un asesor puede haber cambiado
        # de campus con el tiempo; tomamos el más actual vía ROW_NUMBER).
        df_campus = get_df_from_query("""
            WITH RankedOpportunities AS (
                SELECT [OwnerId], [VEC_Campus_de_usuario_del__c],
                    ROW_NUMBER() OVER (PARTITION BY [OwnerId] ORDER BY [CreatedDate] DESC) AS RowNum
                FROM [ETL].[dbo].[Extraer_OportunidadesU4O]
                WHERE [VEC_Campus_de_usuario_del__c] IS NOT NULL
            )
            SELECT [OwnerId] as IdAsesor, [VEC_Campus_de_usuario_del__c] AS Campus
            FROM RankedOpportunities WHERE RowNum = 1;
        """)

        # -----------------------------------------------------------------
        # 2.2 Zona / Estatus del asesor (origen: SIN_Data)
        # -----------------------------------------------------------------
        # Viene de una tabla externa que consolida el status KAM del asesor.
        df_zona = get_df_from_query("""
            SELECT [StatusKAM_Id] as IdAsesor, [StatusKAM_Zona] as Zona, [StatusKAM_Estatus] as EstatusAsesor
            FROM [SIN_Data].[dbo].[Salesforce_StatusKAM]
        """)

        # -----------------------------------------------------------------
        # 2.3 Conteos de oportunidades por empresa (ganadas / perdidas / abiertas)
        # -----------------------------------------------------------------
        # Nota: "abiertas" = cualquier StageName que no sea Cerrada ganada ni
        # Cerrada perdida (incluye Oportunidad, Negociación, etc.).
        df_ganadas = get_df_from_query(
            "SELECT AccountId as IdEmpresa, COUNT(id) as TotalGanadas FROM [ETL].[dbo].[Extraer_OportunidadesU4O] WHERE StageName = 'Cerrada ganada' GROUP BY AccountId")
        df_perdidas = get_df_from_query(
            "SELECT AccountId as IdEmpresa, COUNT(id) as TotalPerdidas FROM [ETL].[dbo].[Extraer_OportunidadesU4O] WHERE StageName = 'Cerrada perdida' GROUP BY AccountId")
        df_abiertas = get_df_from_query(
            "SELECT AccountId as IdEmpresa, COUNT(id) as TotalAbiertas FROM [ETL].[dbo].[Extraer_OportunidadesU4O] WHERE StageName NOT IN ('Cerrada perdida', 'Cerrada ganada') GROUP BY AccountId")

        # -----------------------------------------------------------------
        # 2.4 Primera y última oportunidad por empresa (para antigüedad de relación)
        # -----------------------------------------------------------------
        df_fechas_ops = get_df_from_query(
            "SELECT AccountId as IdEmpresa, MIN(CreatedDate) as PrimeraOportunidad, MAX(CreatedDate) as UltimaOportunidad FROM [ETL].[dbo].[Extraer_OportunidadesU4O] GROUP BY AccountId")

        # -----------------------------------------------------------------
        # 2.5 Ventas por periodo (sólo opps Cerrada ganada)
        # -----------------------------------------------------------------
        # Venta6Meses        : últimos 180 días
        # VentaAñoActual     : últimos 365 días
        # VentaAñoActual_Menos1 : ventana [730d, 365d] — año anterior
        # VentaHistorica     : toda la historia
        # CONVERT(datetime, CloseDate, 103): CloseDate viene como cadena
        #   en formato dd/mm/yyyy (estilo 103 de SQL Server).
        df_range_6months = get_df_from_query(f"""
            SELECT AccountId as IdEmpresa, SUM(Amount) as Venta6Meses
            FROM Extraer_OportunidadesU4O
            WHERE StageName = 'Cerrada ganada' AND CONVERT(datetime, CloseDate, 103) BETWEEN '{six_months_prior}' AND '{current_date_date}'
            GROUP BY AccountId
        """)

        df4 = get_df_from_query(f"""
            SELECT AccountId as IdEmpresa, SUM(Amount) as VentaAñoActual
            FROM Extraer_OportunidadesU4O
            WHERE StageName = 'Cerrada ganada' AND CONVERT(datetime,CloseDate, 103) BETWEEN '{previous_year_date}' AND '{current_date_date}'
            GROUP BY AccountId
        """)

        df5 = get_df_from_query(f"""
            SELECT AccountId 'IdEmpresa', SUM(Amount) 'VentaAñoActual_Menos1'
            FROM Extraer_OportunidadesU4O
            WHERE StageName = 'Cerrada ganada' AND CONVERT(datetime,CloseDate, 103) BETWEEN '{previous_2year_date}' AND '{previous_year_date}'
            GROUP BY AccountId
        """)

        df6 = get_df_from_query("""
            SELECT AccountId 'IdEmpresa', SUM(Amount) 'VentaHistorica'
            FROM Extraer_OportunidadesU4O WHERE StageName = 'Cerrada ganada' GROUP BY AccountId
        """)

        # -----------------------------------------------------------------
        # 2.6 Última actividad por empresa (mezcla dos fuentes)
        # -----------------------------------------------------------------
        # Fuente A: Task/Event más reciente (Extraer_ActividadesU4O.CreatedDate).
        # Fuente B: cambio en OpportunityHistory más reciente vinculado a la
        #           empresa (vía AccountId de la opp).
        # Se hace UNION ALL y luego un groupby + MAX para quedarse con la
        # fecha más reciente de cualquiera de las dos fuentes.
        df8 = get_df_from_query("""
            SELECT  AccountId 'IdEmpresa', MAX(CreatedDate) 'UltimaActividad'
            FROM Extraer_ActividadesU4O GROUP BY AccountId
            UNION ALL
            SELECT  IdEmpresa, MAX(CreatedDate) 'UltimaActividad'
            FROM Extraer_HistoriaOportunidadesU4O q1
            INNER JOIN (SELECT DISTINCT AccountId 'IdEmpresa', Id 'OpportunityId' FROM Extraer_OportunidadesU4O) q2
            ON q1.OpportunityId = q2.OpportunityId GROUP BY IdEmpresa
        """)
        if not df8.empty:
            df8 = df8.groupby('IdEmpresa', as_index=False)['UltimaActividad'].max()
        
        # ================================================================
        # SECCIÓN 3 — DataFrame principal df3 (empresa + asesor + sector)
        # ================================================================
        # Se construye un DataFrame por cada uno de los 4 Industry U4O
        # (Transformación, Comercio, Servicios, Gobierno) y luego se
        # concatenan. El sector específico (VEC_Transformation__c etc.) sólo
        # existe como columna en empresas del Industry correspondiente, por
        # eso el query se parametriza con `col_var`.
        #
        # FILTROS EFECTIVOS:
        #   - INNER JOIN con EmpresasHomologadas → sólo entran empresas cuyo
        #     Name coincide con `NombreOriginal` en la tabla de homologación.
        #   - INNER JOIN con Extraer_AsesoresU4O → sólo entran empresas cuyo
        #     Owner es asesor U4O.
        #   - u.Industry IN los 4 sectores.
        #
        # Empresas fuera del universo Industry=4 sectores o sin homologación
        # se excluyen aquí y no llegan a la salida.
        dfs_clientes = []
        for industry in ['Transformación', 'Comercio', 'Servicios', 'Gobierno']:
            col_var = {
                'Transformación': 'u.VEC_Transformation__c',
                'Comercio': 'u.VEC_Commerce__c',
                'Servicios': 'u.VEC_Services__c',
                'Gobierno': 'u.VEC_Government__c'
                }[industry]

            query_main = f"""
                SELECT DISTINCT u.Id 'IdCRM', u.Name 'NombreEmpresaCRM',
                       CONCAT([BillingStreet],' ',[BillingState],' ', [BillingCity],' ',[BillingCountry]) as 'DireccionCRM',
                       d.NombrePrincipal 'NombreEmpresaHomologado',
                       u.Industry, {col_var} 'Sector',
                       u.OwnerId 'IdAsesor',
                       a.Name 'Asesor', a.LíderAsesor 'LíderAsesor'
                FROM Extraer_EmpresasU4O u
                INNER JOIN EmpresasHomologadas d ON u.Name = d.NombreOriginal
                INNER JOIN (
                    SELECT t1.Id, t1.Name, t1.Email, t2.Name 'LíderAsesor'
                    FROM Extraer_AsesoresU4O t1
                    LEFT JOIN Extraer_AsesoresU4O t2 ON t1.ManagerId = t2.Id
                ) a ON u.OwnerId = a.Id
                WHERE u.Industry = '{industry}'
            """
            dfs_clientes.append(get_df_from_query(query_main))

        df3 = pd.concat(dfs_clientes, ignore_index=True)

        # ================================================================
        # SECCIÓN 4 — Merges masivos (vectorización parte 1)
        # ================================================================
        # Se reemplazan bucles por merges vectorizados. Antes de unir, todos
        # los auxiliares renombran su llave `IdEmpresa` a `IdCRM` para que
        # merge con `on='IdCRM'` no genere columnas duplicadas (y evite
        # MergeError de sufijos).
        aux_dfs = [df_range_6months, df4, df5, df6, df_ganadas, df_perdidas, df_abiertas, df_fechas_ops]
        for df_aux in aux_dfs:
            if 'IdEmpresa' in df_aux.columns:
                df_aux.rename(columns={'IdEmpresa': 'IdCRM'}, inplace=True)

        # LEFT JOIN: mantiene todas las empresas de df3 aunque no tengan ventas
        # ni oportunidades.
        df3 = df3.merge(df_range_6months, on='IdCRM', how='left')
        df3 = df3.merge(df4, on='IdCRM', how='left')
        df3 = df3.merge(df5, on='IdCRM', how='left')
        df3 = df3.merge(df6, on='IdCRM', how='left')
        df3 = df3.merge(df_ganadas, on='IdCRM', how='left')
        df3 = df3.merge(df_perdidas, on='IdCRM', how='left')
        df3 = df3.merge(df_abiertas, on='IdCRM', how='left')
        df3 = df3.merge(df_fechas_ops, on='IdCRM', how='left')

        # Rellenar NaN con 0 en columnas numéricas para que las condiciones
        # posteriores (`> 0`, `== 0`) funcionen sin casos especiales.
        cols_to_fill = ['Venta6Meses', 'VentaAñoActual', 'VentaAñoActual_Menos1',
                        'VentaHistorica', 'TotalGanadas', 'TotalPerdidas', 'TotalAbiertas']
        for col in cols_to_fill:
            if col in df3.columns:
                df3[col] = df3[col].fillna(0)
        
        # ================================================================
        # SECCIÓN 5 — Cálculo de "Actividad" (categoría de recencia)
        # ================================================================
        # Traduce la fecha de última actividad a una etiqueta legible.
        # Valores posibles:
        #   - "Sin registro de actividad en los últimos 3 meses" (si NaT)
        #   - "Menos de un mes" (si < 30 días)
        #   - "N meses" (N = DiasDiff/30 redondeado)
        if 'IdEmpresa' in df8.columns:
            df8.rename(columns={'IdEmpresa': 'IdCRM'}, inplace=True)
        df3 = df3.merge(df8, on='IdCRM', how='left')

        df3['UltimaActividad'] = pd.to_datetime(df3['UltimaActividad'], errors='coerce')
        df3['DiasDiff'] = (current_date - df3['UltimaActividad']).dt.days

        cond_null = df3['UltimaActividad'].isna()
        cond_meses = (df3['DiasDiff'] / 30).round()

        # np.where anidado para tres ramas: null → sin registro / <1 mes → "Menos de un mes" / resto → "N meses".
        df3['Actividad'] = np.where(cond_null,
                                    "Sin registro de actividad en los últimos 3 meses",
                                    np.where(cond_meses < 1,
                                             "Menos de un mes",
                                             cond_meses.astype(str).str.replace(r'\.0$', '', regex=True) + " meses"))

        # ================================================================
        # SECCIÓN 6 — Cálculo de EstatusSeguimiento_Zona
        # ================================================================
        # Este es el núcleo de negocio del script. Combina:
        #   (a) ¿Hay actividad registrada en los últimos 3 meses?
        #   (b) ¿Hay venta cerrada ganada en el año actual?
        #   (c) ¿Hay una empresa "hermana" (mismo NombreEmpresaHomologado)
        #       que sí tenga actividad/venta aunque esta no?
        #
        # La pregunta (c) maneja el caso de duplicados en CRM: dos cuentas
        # con nombres ligeramente distintos pero que se homologan al mismo
        # nombre canónico. Si una de ellas tiene venta/actividad, la otra
        # "hereda" esa señal pero etiquetada como "(Otro asesor)" o
        # "(Mismo asesor)" según quién lleve la hermana.
        df3['EstatusSeguimiento_Zona'] = ''

        # Condiciones base reutilizadas en varias ramas.
        cond_actividad_existe = df3['Actividad'] != "Sin registro de actividad en los últimos 3 meses"
        cond_venta_existe = df3['VentaAñoActual'] > 0

        # -----------------------------------------------------------------
        # 6.1 Casos directos: no necesitan mirar a las hermanas
        # -----------------------------------------------------------------
        df3.loc[cond_actividad_existe & cond_venta_existe, 'EstatusSeguimiento_Zona'] = 'Con actividad y con ventas'
        df3.loc[(~cond_actividad_existe) & cond_venta_existe, 'EstatusSeguimiento_Zona'] = 'Sin actividad y con ventas'
        df3.loc[cond_actividad_existe & (~cond_venta_existe), 'EstatusSeguimiento_Zona'] = 'Con actividad y sin ventas'

        # -----------------------------------------------------------------
        # 6.2 Self-join por NombreEmpresaHomologado para mirar "hermanas"
        # -----------------------------------------------------------------
        # Creamos una versión reducida con la PRIMERA ocurrencia de cada
        # NombreEmpresaHomologado y la unimos con df3. Ahora cada fila tiene
        # además columnas `_match` que describen la primera hermana encontrada.
        # (En el script original se usaba `match.iloc[0]` dentro de un loop;
        # aquí se vectoriza con groupby().first().)
        df_first_match = df3.groupby('NombreEmpresaHomologado').first().reset_index()
        df3 = df3.merge(df_first_match, on='NombreEmpresaHomologado', suffixes=('', '_match'), how='left')

        # Máscara base: sólo interesa reclasificar filas que SIN MATCH serían
        # "Sin actividad y sin venta". Si ya tienen venta/actividad propia,
        # no se tocan (ya se asignaron en 6.1).
        mask_base = (df3['VentaAñoActual'] == 0) & (df3['Actividad'] == "Sin registro de actividad en los últimos 3 meses")

        asesor_diff = df3['Asesor'] != df3['Asesor_match']
        match_con_actividad = df3['Actividad_match'] != "Sin registro de actividad en los últimos 3 meses"
        match_con_venta = df3['VentaAñoActual_match'] > 0
        lider_diff = df3['LíderAsesor'] != df3['LíderAsesor_match']
        nombre_crm_diff = df3['NombreEmpresaCRM'] != df3['NombreEmpresaCRM_match']

        # -----------------------------------------------------------------
        # 6.3 RAMA 1: la hermana la lleva OTRO asesor
        # -----------------------------------------------------------------
        # La empresa actual no tiene señales, pero otra cuenta homologada
        # con el mismo nombre está siendo atendida por otro asesor.
        # Se marca "(Otro asesor)" y —si además son de distinto Líder—
        # se alimenta `EstatusSeguimiento_EC` (la vista de Dirección EC).
        criterio_rama1 = mask_base & asesor_diff

        # 6.3.1 Hermana con actividad
        c1_1 = criterio_rama1 & match_con_actividad

        # 6.3.1.A Hermana con actividad Y con venta
        c1_1_A = c1_1 & match_con_venta
        df3.loc[c1_1_A & lider_diff, ['EstatusSeguimiento_Zona', 'EstatusSeguimiento_EC']] = [
            'Sin actividad y sin venta', 'Con actividad y venta (Otro asesor)']
        df3.loc[c1_1_A & (~lider_diff), 'EstatusSeguimiento_Zona'] = 'Con actividad y venta (Otro asesor)'

        # 6.3.1.B Hermana con actividad pero sin venta
        c1_1_B = c1_1 & (~match_con_venta)
        df3.loc[c1_1_B & lider_diff, ['EstatusSeguimiento_Zona', 'EstatusSeguimiento_EC']] = [
            'Sin actividad y sin venta', 'Con actividad y sin venta (Otro asesor)']
        df3.loc[c1_1_B & (~lider_diff), 'EstatusSeguimiento_Zona'] = 'Con actividad y sin venta (Otro asesor)'

        # 6.3.2 Hermana sin actividad → nadie la está atendiendo: todos huérfanos
        c1_2 = criterio_rama1 & (~match_con_actividad)
        df3.loc[c1_2, 'EstatusSeguimiento_Zona'] = 'Sin actividad y sin venta'

        # -----------------------------------------------------------------
        # 6.4 RAMA 2: MISMO asesor pero diferente nombre CRM
        # -----------------------------------------------------------------
        # Dos cuentas homologadas al mismo nombre, mismo asesor, pero
        # distintos NombreEmpresaCRM (probablemente duplicados creados por
        # él mismo). Se etiqueta "(Mismo asesor)".
        criterio_rama2 = mask_base & (~asesor_diff) & nombre_crm_diff

        c2_1 = criterio_rama2 & match_con_venta
        df3.loc[c2_1 & lider_diff, ['EstatusSeguimiento_Zona', 'EstatusSeguimiento_EC']] = ['Sin actividad',
                                                                                            'Con actividad y venta (Mismo asesor)']
        df3.loc[c2_1 & (~lider_diff), 'EstatusSeguimiento_Zona'] = 'Con actividad y venta (Mismo asesor)'

        c2_2 = criterio_rama2 & (~match_con_venta)
        df3.loc[c2_2, 'EstatusSeguimiento_Zona'] = 'Con actividad y sin venta (Mismo asesor)'

        # -----------------------------------------------------------------
        # 6.5 Fallback: sin asignación previa, sin venta, sin actividad
        # -----------------------------------------------------------------
        # Todo lo que no cayó en 6.1–6.4 y sigue vacío se marca como el caso
        # más frío: sin actividad, sin venta.
        mask_residual = (df3['EstatusSeguimiento_Zona'] == '') & (df3['VentaAñoActual'] == 0) & (
                df3['Actividad'] == "Sin registro de actividad en los últimos 3 meses")
        df3.loc[mask_residual, 'EstatusSeguimiento_Zona'] = 'Sin actividad y sin venta'

        # -----------------------------------------------------------------
        # 6.6 Sobrescritura final: sin actividad pero CON venta del año
        # -----------------------------------------------------------------
        # En el script original esta asignación era al final y sobrescribía
        # cualquier otra. Se mantiene ese comportamiento: si no hay actividad
        # pero sí hay venta del año, gana la etiqueta "Sin actividad y con venta".
        mask_simple_venta = (df3['Actividad'] == "Sin registro de actividad en los últimos 3 meses") & (
                df3['VentaAñoActual'] > 0)
        df3.loc[mask_simple_venta, 'EstatusSeguimiento_Zona'] = 'Sin actividad y con venta'
        
        # ================================================================
        # SECCIÓN 7 — Merge final de Campus y Zona del asesor
        # ================================================================
        # Estos dos atributos vienen por asesor (no por empresa). Si el
        # origen está vacío, se inicializan columnas vacías para mantener
        # el esquema del CSV estable.
        if not df_campus.empty:
            df3 = df3.merge(df_campus, on='IdAsesor', how='left')
        else:
            df3['Campus'] = ''

        if not df_zona.empty:
            df3 = df3.merge(df_zona, on='IdAsesor', how='left')
        else:
            df3['Zona'] = ''
            df3['EstatusAsesor'] = ''

        # Aseguramos que las columnas clave existan y estén limpias de nulos.
        cols_finales_fill = ['Campus', 'Zona', 'EstatusAsesor', 'EstatusSeguimiento_EC']
        for col in cols_finales_fill:
            if col not in df3.columns:
                df3[col] = ''
            df3[col] = df3[col].fillna('')

        # Fechas en formato ISO (YYYY-MM-DD) para consumo downstream.
        for col in ['PrimeraOportunidad', 'UltimaOportunidad']:
            if col in df3.columns:
                df3[col] = pd.to_datetime(df3[col], errors='coerce').dt.strftime('%Y-%m-%d')

        df3 = df3.fillna('').infer_objects(copy=False)

        # ================================================================
        # SECCIÓN 8 — Exportación a CSV
        # ================================================================
        # Columnas finales del CSV. Orden fijo para consumo downstream.
        columns_to_export = [
            'IdCRM',
            'NombreEmpresaHomologado',
            'NombreEmpresaCRM',
            'DireccionCRM',
            'Industry',
            'Sector',
            'Asesor',
            'Campus',
            'Zona',
            'LíderAsesor',
            'EstatusSeguimiento_Zona',
            'VentaHistorica',
            'Venta6Meses',
            'VentaAñoActual',
            'VentaAñoActual_Menos1',
            'TotalGanadas',
            'TotalPerdidas',
            'TotalAbiertas',
            'PrimeraOportunidad',
            'UltimaOportunidad',
            'EstatusAsesor'
            ]

        # Blindaje: si alguna columna no llegó a crearse, se agrega vacía.
        for col in columns_to_export:
            if col not in df3.columns:
                df3[col] = ''

        # El CSV se escribe al lado del script, no en un path absoluto.
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_path = os.path.join(script_dir, 'ActividadRecompra_U4O.csv')

        df3[columns_to_export].to_csv(output_path, index=False, encoding='utf-8')

        # ================================================================
        # SECCIÓN 9 — INSERT a Reporte_AnalisisAtencionU4O (nivel contacto)
        # ================================================================
        # Mientras el CSV resume A NIVEL EMPRESA, esta tabla detalla el
        # último contacto atendido de cada empresa y sus métricas temporales.
        # La lógica se ejecuta completamente en SQL Server con CTEs.
        print("Generando e insertando Reporte de Análisis de Atención...")
        
        query_analisis_insert = """
        -- ============================================================
        -- Limpieza previa: la tabla es un snapshot, no histórico.
        -- ============================================================
        TRUNCATE TABLE [dbo].[Reporte_AnalisisAtencionU4O];

        -- ============================================================
        -- CTE 1: Resumen de oportunidades por empresa
        -- Captura la fecha de la opp más reciente y la última Cerrada Ganada.
        -- Se usa para calcular antigüedad (FechaOportunidadMasReciente,
        -- FechaUltimaCerradaGanada) en el INSERT final.
        -- ============================================================
        ;WITH CTE_ResumenOportunidades AS (
            SELECT [AccountId], MAX([CreatedDate]) AS FechaUltimaOpo,
                MAX(CASE WHEN [StageName] = 'Cerrada Ganada' THEN [CloseDate] END) AS FechaUltimaGanada
            FROM [ETL].[dbo].[Extraer_OportunidadesU4O] WHERE [AccountId] IS NOT NULL GROUP BY [AccountId]
        ),
        -- ============================================================
        -- CTE 2: Universo de empresas + flag Con/Sin Oportunidades
        -- LEFT JOIN: deja entrar empresas aunque no tengan opps.
        -- ============================================================
        CTE_EmpresasUniverso AS (
            SELECT E.[Id] AS EmpresaId, E.[Name] AS EmpresaNombre,
                CASE WHEN O.[AccountId] IS NOT NULL THEN 'Con Oportunidades' ELSE 'Sin Oportunidades' END AS TipoEmpresa,
                O.FechaUltimaOpo, O.FechaUltimaGanada
            FROM [ETL].[dbo].[Extraer_EmpresasU4O] E
            LEFT JOIN CTE_ResumenOportunidades O ON E.[Id] = O.[AccountId]
        ),
        -- ============================================================
        -- CTE 3: Silo de asesores (para validar que la actividad venga del equipo)
        -- ============================================================
        CTE_AsesoresEquipo AS (
            SELECT [Id] AS AsesorId, [Name] AS AsesorNombre FROM [ETL].[dbo].[Extraer_AsesoresU4O]
        ),
        -- ============================================================
        -- CTE 4: Consolidado de actividades (3 fuentes via UNION ALL)
        -- Cada fila representa una actividad vinculada a (EmpresaId, ContactoId).
        --
        -- FUENTE (1) — Task/Event nativos:
        --   AccountId viene directo del registro Task/Event.
        --   Owner del Task/Event = Asesor potencial.
        --
        -- FUENTE (2) — EAC linkeado a Contact.AccountId:
        --   El EAC (ActivityMetric) se guarda por contacto.
        --   Se toma la AccountId nativa del contacto como empresa.
        --
        -- FUENTE (3) — EAC linkeado a Opp.AccountId (puente adicional):
        --   Cuando el contacto es VEC_BusinessContact__c de una opp cuya
        --   cuenta DIFIERE de su AccountId nativa, agregamos una fila
        --   extra para que el EAC aparezca también en esa empresa.
        --   Caso de uso: contacto principal de opp en empresa A pero con
        --   AccountId histórico en empresa B — sin este puente, el EAC
        --   sólo aparecería en B y la empresa A (la realmente relevante
        --   para la relación comercial) quedaría invisible.
        --   Se filtra con `O.AccountId <> Contact.AccountId` para no
        --   duplicar con (2).
        -- ============================================================
        CTE_ConsolidadoActividades AS (
            -- (1) Task/Event nativos con AccountId
            SELECT A.[AccountId] AS EmpresaId, A.[WhoId] AS ContactoId,
                ISNULL(C.[Nombre_Completo__c], 'Actividad sin Contacto') AS ContactoNombre,
                A.[OwnerId] AS AsesorId, A.[Subject] AS Asunto, TRY_CAST(A.[CreatedDate] AS DATETIME) AS FechaActividad,
                'Salesforce Standard' AS Origen
            FROM [ETL].[dbo].[Extraer_ActividadesU4O] A
            LEFT JOIN [ETL].[dbo].[Extraer_ContactosU4O] C ON A.[WhoId] = C.[Id] WHERE A.[AccountId] IS NOT NULL
            UNION ALL
            -- (2) EAC linkeado al AccountId nativo del contacto
            SELECT C.[AccountId] AS EmpresaId, E.[BaseId] AS ContactoId, C.[Nombre_Completo__c] AS ContactoNombre,
                NULL AS AsesorId, 'Sincronización Einstein' AS Asunto, TRY_CAST(E.[LastActivityDateTime] AS DATETIME) AS FechaActividad,
                'Einstein CRM' AS Origen
            FROM [ETL].[dbo].[Extraer_EinsteinCRM] E
            INNER JOIN [ETL].[dbo].[Extraer_ContactosU4O] C ON E.[BaseId] = C.[Id] WHERE E.[BaseType] = 'Contact'
            UNION ALL
            -- (3) EAC linkeado al AccountId de la opp (puente contacto↔empresa)
            SELECT O.[AccountId] AS EmpresaId, E.[BaseId] AS ContactoId, C.[Nombre_Completo__c] AS ContactoNombre,
                NULL AS AsesorId, 'Sincronización Einstein (vía Opp)' AS Asunto, TRY_CAST(E.[LastActivityDateTime] AS DATETIME) AS FechaActividad,
                'Einstein CRM' AS Origen
            FROM [ETL].[dbo].[Extraer_EinsteinCRM] E
            INNER JOIN [ETL].[dbo].[Extraer_ContactosU4O] C ON E.[BaseId] = C.[Id]
            INNER JOIN (
                SELECT DISTINCT VEC_BusinessContact__c, AccountId
                FROM [ETL].[dbo].[Extraer_OportunidadesU4O]
                WHERE AccountId IS NOT NULL AND VEC_BusinessContact__c IS NOT NULL
            ) O ON O.VEC_BusinessContact__c = E.BaseId
            WHERE E.BaseType = 'Contact'
            AND O.AccountId <> ISNULL(C.AccountId, '')
        ),
        -- ============================================================
        -- CTE 5: Cálculos temporales + ranking
        --
        -- Por cada empresa se calcula:
        --   - FechaUltimo    : fecha de la actividad actual (fila).
        --   - FechaPenultimo : LAG sobre la misma empresa+contacto ordenado
        --                      por fecha ASC → la actividad anterior del
        --                      mismo contacto en la misma empresa. Permite
        --                      calcular DiasEntreContactos.
        --   - RankingActividad: ROW_NUMBER sobre la empresa ordenada por
        --                      fecha DESC → 1 = actividad más reciente de
        --                      esa empresa.
        --
        -- FILTRO WHERE:
        --   Sólo se consideran actividades cuyo asesor está en el silo U4O,
        --   EXCEPTO las de Origen 'Einstein CRM' (que no tienen AsesorId
        --   porque EAC no expone el owner a nivel métrica). Estas últimas
        --   pasan siempre — la presencia del EAC ya es señal de atención.
        -- ============================================================
        CTE_CalculoTemporal AS (
            SELECT EU.EmpresaId, EU.EmpresaNombre, EU.TipoEmpresa, EU.FechaUltimaOpo, EU.FechaUltimaGanada,
                UA.ContactoId, UA.ContactoNombre, UA.AsesorId, ASE.AsesorNombre, UA.Asunto, UA.Origen,
                UA.FechaActividad AS FechaUltimo,
                LAG(UA.FechaActividad) OVER (PARTITION BY EU.EmpresaId, ISNULL(UA.ContactoId, 'SIN_CONTACTO') ORDER BY UA.FechaActividad ASC) AS FechaPenultimo,
                ROW_NUMBER() OVER (PARTITION BY EU.EmpresaId ORDER BY UA.FechaActividad DESC) AS RankingActividad
            FROM CTE_ConsolidadoActividades UA
            INNER JOIN CTE_EmpresasUniverso EU ON UA.EmpresaId = EU.EmpresaId
            LEFT JOIN CTE_AsesoresEquipo ASE ON UA.AsesorId = ASE.AsesorId
            WHERE (UA.AsesorId IN (SELECT AsesorId FROM CTE_AsesoresEquipo) OR UA.Origen = 'Einstein CRM')
        )
        -- ============================================================
        -- INSERT FINAL
        -- Sólo se queda la fila con RankingActividad = 1 por empresa
        -- (la actividad más reciente). Empresas sin ninguna actividad
        -- no aparecen en el reporte (INNER JOIN las excluye).
        -- ============================================================
        INSERT INTO [dbo].[Reporte_AnalisisAtencionU4O] (
            EmpresaId, EmpresaNombre, TipoEmpresa, ContactoId, ContactoNombre,
            AsesorId, AsesorNombre, UltimoAsunto, FuenteDato, FechaUltimoContacto,
            FechaContactoPrevio, FechaOportunidadMasReciente, FechaUltimaCerradaGanada,
            DiasEntreContactos, DiasDesdeUltimoContacto, Dias_FechaOportunidadMasReciente,
            Dias_FechaUltimaCerradaGanada, TiempoExactoDiferencia
        )
        SELECT EmpresaId, EmpresaNombre, TipoEmpresa, ContactoId, ContactoNombre, AsesorId, AsesorNombre,
            Asunto, Origen, FechaUltimo, FechaPenultimo, FechaUltimaOpo, FechaUltimaGanada,
            DATEDIFF(DAY, FechaPenultimo, FechaUltimo), DATEDIFF(DAY, FechaUltimo, GETDATE()),
            DATEDIFF(DAY, FechaUltimaOpo , GETDATE()), DATEDIFF(DAY, FechaUltimaGanada , GETDATE()),
            CASE WHEN FechaPenultimo IS NULL THEN 'Sin contacto previo registrado' END
        FROM CTE_CalculoTemporal WHERE RankingActividad = 1;
        """
        
        cursor.execute(query_analisis_insert)
        conn_sql_server.commit()  # Importante para asegurar la persistencia
        print("Reporte de Análisis insertado correctamente en ETL.")
    
    except Exception as e:
        print(f"Error durante el proceso: {str(e)}")
        if conn_sql_server:
            conn_sql_server.rollback()
    
    finally:
        if cursor:
            cursor.close()
        if conn_sql_server:
            conn_sql_server.close()
    
    print('Mapeo Estrategico Empresas | Tiempo de ejecución :', datetime.now() - startTime)


if __name__ == "__main__":
    main(None)