import pandas as pd
import json
import logging
import os
import sys

# Directorio del script (para resolver rutas relativas)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Agregar directorio padre al path para importar Conexiones
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))
import Conexiones

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def main(origen):
    conn, cursor = Conexiones.connect_SINDATA_local_sql(origen)

    query = """
        SELECT FechaAnalytics, IdOportunidad, EtapaDetalle,
               InicioEjecucion, TerminoEjecucion, FechaCierreGroup, CECO, Importe,
               PropietarioOportunidad,
               NombrePrincipal, NombreOportunidad,
               CONCAT(ISNULL(NombrePrincipal,''), ' / ', ISNULL(NombreOportunidad,'')) AS Proyecto,
               CASE WHEN Zona IN ('BRASIL & PERÚ','COLOMBIA & PANAMÁ','ECUADOR','BOLIVIA & CHILE','CENTRO AMÉRICA & CARIBE','USA') THEN 'INTERNACIONAL'
                    WHEN Zona IN ('CENTRO','OCCIDENTE') THEN 'CENTRO & OCCIDENTE'
                    ELSE Zona END AS ZonaAgrupada
        FROM [SIN_Data].[dbo].[SalesforceTablero_Historico_Total]
        WHERE EtapaDetalle = 'Cerrada ganada'
          AND CONVERT(DATE, FechaAnalytics, 103) >= '2026-03-01'
          AND FechaCierreGroup >= '2025-08-01'
        ORDER BY IdOportunidad, FechaAnalytics
    """

    logging.info("Consultando snapshots de oportunidades Cerrada ganada (últimos 365 días)...")
    cursor.execute(query)
    rows = cursor.fetchall()
    columns = [col[0] for col in cursor.description]
    conn.close()
    df = pd.DataFrame.from_records(rows, columns=columns)
    logging.info(f"Registros obtenidos: {len(df)}")

    if df.empty:
        logging.warning("No se encontraron registros.")
        return

    # Convertir FechaAnalytics de string DD/MM/YYYY a datetime para ordenar correctamente
    df = df.assign(FechaAnalytics=pd.to_datetime(df['FechaAnalytics'], format='%d/%m/%Y'))

    # Detectar cambios comparando valores no nulos consecutivos por oportunidad
    df = df.sort_values(['IdOportunidad', 'FechaAnalytics']).copy()

    # Para InicioEjecucion: propagar último valor no nulo y comparar
    df.loc[:, 'InicioNoNulo'] = df.groupby('IdOportunidad')['InicioEjecucion'].ffill()
    df.loc[:, 'InicioAnteriorNoNulo'] = df.groupby('IdOportunidad')['InicioNoNulo'].shift(1)
    df.loc[:, 'CambioInicio'] = (
        df['InicioNoNulo'].notna() &
        df['InicioAnteriorNoNulo'].notna() &
        (df['InicioNoNulo'] != df['InicioAnteriorNoNulo'])
    ).astype(int)

    # Para TerminoEjecucion: propagar último valor no nulo y comparar
    df.loc[:, 'TerminoNoNulo'] = df.groupby('IdOportunidad')['TerminoEjecucion'].ffill()
    df.loc[:, 'TerminoAnteriorNoNulo'] = df.groupby('IdOportunidad')['TerminoNoNulo'].shift(1)
    df.loc[:, 'CambioTermino'] = (
        df['TerminoNoNulo'].notna() &
        df['TerminoAnteriorNoNulo'].notna() &
        (df['TerminoNoNulo'] != df['TerminoAnteriorNoNulo'])
    ).astype(int)

    # Resumen por oportunidad
    resumen = df.groupby('IdOportunidad').agg(
        CambiosInicioEjecucion=('CambioInicio', 'sum'),
        CambiosTerminoEjecucion=('CambioTermino', 'sum'),
        TotalSnapshots=('FechaAnalytics', 'count'),
        PrimerSnapshot=('FechaAnalytics', 'min'),
        UltimoSnapshot=('FechaAnalytics', 'max')
    ).reset_index()

    # Primer y último valor NO nulo de InicioEjecucion y TerminoEjecucion
    df_inicio = df.dropna(subset=['InicioEjecucion']).groupby('IdOportunidad')['InicioEjecucion']
    resumen = resumen.merge(df_inicio.first().rename('PrimerInicioRegistrado'), on='IdOportunidad', how='left')
    resumen = resumen.merge(df_inicio.last().rename('UltimoInicioRegistrado'), on='IdOportunidad', how='left')

    df_termino = df.dropna(subset=['TerminoEjecucion']).groupby('IdOportunidad')['TerminoEjecucion']
    resumen = resumen.merge(df_termino.first().rename('PrimerTerminoRegistrado'), on='IdOportunidad', how='left')
    resumen = resumen.merge(df_termino.last().rename('UltimoTerminoRegistrado'), on='IdOportunidad', how='left')

    # Días desde primer dato de inicio hasta el primer cambio detectado
    df_primer_dato = df.dropna(subset=['InicioEjecucion']).groupby('IdOportunidad')['FechaAnalytics'].first().rename('FechaPrimerDatoInicio')
    df_primer_cambio = df[df['CambioInicio'] == 1].groupby('IdOportunidad')['FechaAnalytics'].first().rename('FechaPrimerCambioInicio')
    resumen = resumen.merge(df_primer_dato, on='IdOportunidad', how='left')
    resumen = resumen.merge(df_primer_cambio, on='IdOportunidad', how='left')
    resumen = resumen.assign(
        DiasHastaPrimerCambioInicio=(
            resumen['FechaPrimerCambioInicio'] - resumen['FechaPrimerDatoInicio']
        ).dt.days
    )

    # Historial granular de cambios de InicioEjecucion (para barra de movimientos en dashboard)
    # Captura cada push: fecha del snapshot donde se detectó, valor antes, valor después y días empujados
    cambios_inicio_df = df[df['CambioInicio'] == 1].copy()
    if not cambios_inicio_df.empty:
        cambios_inicio_df = cambios_inicio_df.assign(
            fecha_snapshot=cambios_inicio_df['FechaAnalytics'].dt.strftime('%Y-%m-%d'),
            valor_antes=pd.to_datetime(cambios_inicio_df['InicioAnteriorNoNulo']).dt.strftime('%Y-%m-%d'),
            valor_despues=pd.to_datetime(cambios_inicio_df['InicioNoNulo']).dt.strftime('%Y-%m-%d'),
            dias_empujados=(
                pd.to_datetime(cambios_inicio_df['InicioNoNulo']) -
                pd.to_datetime(cambios_inicio_df['InicioAnteriorNoNulo'])
            ).dt.days
        )

        def _historial_json(grp):
            registros = grp[['fecha_snapshot', 'valor_antes', 'valor_despues', 'dias_empujados']].to_dict(orient='records')
            return json.dumps(registros, ensure_ascii=False)

        historial = cambios_inicio_df.groupby('IdOportunidad', group_keys=False).apply(_historial_json, include_groups=False).rename('HistorialCambiosInicio')
        resumen = resumen.merge(historial, on='IdOportunidad', how='left')
    else:
        resumen = resumen.assign(HistorialCambiosInicio=None)

    # Oportunidades sin cambios → array vacío (más fácil de parsear en JS que NaN/null)
    resumen = resumen.assign(HistorialCambiosInicio=resumen['HistorialCambiosInicio'].fillna('[]'))

    # CECO del último snapshot por oportunidad
    df_ultimo = df.drop_duplicates(subset='IdOportunidad', keep='last')[['IdOportunidad', 'CECO', 'Importe', 'PropietarioOportunidad', 'NombrePrincipal', 'NombreOportunidad', 'Proyecto', 'ZonaAgrupada', 'FechaCierreGroup']]
    resumen = resumen.merge(df_ultimo, on='IdOportunidad', how='left')

    # Cruzar email de propietario desde ETL.dbo.Extraer_AsesoresU4O
    conn_etl, cursor_etl = Conexiones.connect_ETL_local_sql(origen)
    cursor_etl.execute("SELECT [Name], [Email] FROM [ETL].[dbo].[Extraer_AsesoresU4O]")
    rows_email = cursor_etl.fetchall()
    cols_email = [c[0] for c in cursor_etl.description]
    conn_etl.close()
    df_emails = pd.DataFrame.from_records(rows_email, columns=cols_email)
    resumen = resumen.merge(df_emails, left_on='PropietarioOportunidad', right_on='Name', how='left')
    resumen = resumen.rename(columns={'Email': 'EmailPropietario'}).drop(columns=['Name'], errors='ignore')

    # Columna Iniciado: hoy >= UltimoInicioRegistrado
    hoy = pd.Timestamp.today().normalize()
    resumen = resumen.assign(
        Iniciado=pd.to_datetime(resumen['UltimoInicioRegistrado']).apply(
            lambda x: 'Si' if pd.notna(x) and x <= hoy else 'No'
        ),
        TieneCECO=resumen['CECO'].apply(
            lambda x: 'Si' if pd.notna(x) and str(x).strip() != '' else 'No'
        )
    )

    # Clasificación de riesgo
    def clasificar_riesgo(row):
        if row['Iniciado'] == 'Si' and row['TieneCECO'] == 'Si':
            return 'Nulo'
        elif row['Iniciado'] == 'Si' and row['TieneCECO'] == 'No':
            return 'Alto'
        elif row['Iniciado'] == 'No' and row['TieneCECO'] == 'Si':
            return 'Medio'
        else:  # No iniciado, sin CECO
            return 'Nulo'

    resumen = resumen.assign(Riesgo=resumen.apply(clasificar_riesgo, axis=1))

    # Clasificación de Riesgo Asertividad (solo para proyectos con cambios)
    # Bajo (0-14 días): Ajuste de captura
    # Medio (15-30 días): Ajuste tardío
    # Alto (>30 días): Falta de asertividad
    def clasificar_asertividad(row):
        dias = row['DiasHastaPrimerCambioInicio']
        if pd.isna(dias):
            return 'Sin cambios'
        elif dias <= 14:
            return 'Bajo (0-14 dias)'
        elif dias <= 30:
            return 'Medio (15-30 dias)'
        else:
            return 'Alto (>30 dias)'

    resumen = resumen.assign(RiesgoAsertividad=resumen.apply(clasificar_asertividad, axis=1))

    # Diferencia en días entre primer y último registro
    resumen = resumen.assign(
        DiferenciaInicio_Dias=(
            pd.to_datetime(resumen['UltimoInicioRegistrado']) - pd.to_datetime(resumen['PrimerInicioRegistrado'])
        ).dt.days,
        DiferenciaTermino_Dias=(
            pd.to_datetime(resumen['UltimoTerminoRegistrado']) - pd.to_datetime(resumen['PrimerTerminoRegistrado'])
        ).dt.days,
        DiasVentaInicio=(
            pd.to_datetime(resumen['UltimoInicioRegistrado']) - pd.to_datetime(resumen['FechaCierreGroup'])
        ).dt.days
    )

    resumen = resumen.sort_values('CambiosInicioEjecucion', ascending=False)

    output_file = os.path.join(SCRIPT_DIR, 'Monitoreo_FechasProyecto.csv')
    resumen.to_csv(output_file, index=False, encoding='utf-8-sig', quoting=1)
    logging.info(f"Resumen exportado a {output_file}")
    logging.info(f"Total oportunidades analizadas: {len(resumen)}")
    logging.info(f"Oportunidades con cambios en InicioEjecucion: {(resumen['CambiosInicioEjecucion'] > 0).sum()}")
    logging.info(f"Oportunidades con cambios en TerminoEjecucion: {(resumen['CambiosTerminoEjecucion'] > 0).sum()}")
    importe_alto = resumen.loc[resumen['Riesgo'] == 'Alto', 'Importe'].sum()
    importe_medio = resumen.loc[resumen['Riesgo'] == 'Medio', 'Importe'].sum()
    logging.info(f"Importe en Riesgo Alto: ${importe_alto:,.2f}")
    logging.info(f"Importe en Riesgo Medio: ${importe_medio:,.2f}")

    # Fecha de extracción: FechaAnalytics más reciente
    fecha_extraccion = df['FechaAnalytics'].max().strftime('%d/%b/%Y')

    # Generar HTML autónomo con datos embebidos
    generar_html_autonomo(resumen, fecha_extraccion)

    # Subir a SharePoint
    subir_sharepoint(os.path.join(SCRIPT_DIR, 'Dashboard_Riesgo_Autonomo.html'))

    return resumen


def subir_sharepoint(archivo_local):
    import shutil
    carpeta_destino = os.path.expanduser(
        '~/OneDrive - Instituto Tecnologico y de Estudios Superiores de Monterrey/'
        'Power U4O sin fronteras - InteligenciaComercialU4O'
    )

    logging.info(f"Copiando {archivo_local} a SharePoint (OneDrive sync)...")
    try:
        destino = os.path.join(carpeta_destino, os.path.basename(archivo_local))
        shutil.copy2(archivo_local, destino)
        logging.info(f"Archivo copiado exitosamente: {destino}")
    except Exception as e:
        logging.error(f"Error al copiar a SharePoint: {e}")


def generar_html_autonomo(resumen, fecha_extraccion='--'):
    import json
    import re

    # Leer el template HTML
    with open(os.path.join(SCRIPT_DIR, 'Dashboard_Riesgo_CerradoGanado.html'), 'r', encoding='utf-8') as f:
        html_template = f.read()

    # Inyectar fecha de extracción en el badge
    html_template = html_template.replace('Extracción: --', f'Extracción: {fecha_extraccion}')

    # Convertir datos a JSON
    records = resumen.fillna('').to_dict(orient='records')
    json_data = json.dumps(records, ensure_ascii=False, default=str)

    # Reemplazar todo el bloque desde "async function loadData" hasta el cierre del try/allData
    # Buscar con regex el bloque de loadData y reemplazar hasta después del mapeo de allData
    new_load_block = f"""async function loadData() {{
        try {{
            const rawData = {json_data};

            allData = rawData.map(r => ({{
                id: r.IdOportunidad || '',
                cambiosInicio: parseInt(r.CambiosInicioEjecucion) || 0,
                cambiosTermino: parseInt(r.CambiosTerminoEjecucion) || 0,
                ceco: r.CECO || '',
                importe: parseFloat(r.Importe) || 0,
                iniciado: r.Iniciado || '',
                tieneCECO: r.TieneCECO || '',
                riesgo: r.Riesgo || '',
                riesgoAsertividad: r.RiesgoAsertividad || '',
                diasHastaCambio: parseFloat(r.DiasHastaPrimerCambioInicio) || 0,
                diasInicio: parseFloat(r.DiferenciaInicio_Dias) || 0,
                diasTermino: parseFloat(r.DiferenciaTermino_Dias) || 0,
                primerInicio: r.PrimerInicioRegistrado || '',
                ultimoInicio: r.UltimoInicioRegistrado || '',
                fechaCierre: r.FechaCierreGroup || '',
                diasVentaInicio: (r.DiasVentaInicio === '' || r.DiasVentaInicio === null || r.DiasVentaInicio === undefined) ? null : parseInt(r.DiasVentaInicio),
                historialCambiosInicio: (() => {{ try {{ return JSON.parse(r.HistorialCambiosInicio || '[]'); }} catch(e) {{ return []; }} }})(),
                zona: r.ZonaAgrupada || '',
                propietario: r.PropietarioOportunidad || '',
                propietarioEmail: r.EmailPropietario || '',
                nombrePrincipal: r.NombrePrincipal || '',
                nombreOportunidad: r.NombreOportunidad || '',
                proyecto: r.Proyecto || ''
            }}));"""

    # Reemplazar desde "async function loadData()" hasta "});", que es el cierre del map
    pattern = r'async function loadData\(\)\s*\{.*?proyecto:.*?\}\);'
    html_autonomo = re.sub(pattern, new_load_block, html_template, count=1, flags=re.DOTALL)

    output_html = os.path.join(SCRIPT_DIR, 'Dashboard_Riesgo_Autonomo.html')
    with open(output_html, 'w', encoding='utf-8') as f:
        f.write(html_autonomo)

    logging.info(f"HTML autónomo generado: {output_html}")


if __name__ == "__main__":
    import sys
    origen = sys.argv[1] if len(sys.argv) > 1 else None
    main(origen)
