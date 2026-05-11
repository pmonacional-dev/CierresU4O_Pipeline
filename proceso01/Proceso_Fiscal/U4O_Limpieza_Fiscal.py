from datetime import datetime
import sys
import os
import warnings
# Agregar el directorio raíz al path para importar Conexiones
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import Conexiones
import logging
import pandas as pd
import json

# Silenciar ruido de pandas 2.x:
# - UserWarning: pd.read_sql con pyodbc (no SQLAlchemy)
# - FutureWarning: aviso de migración a Copy-on-Write para asignaciones de columnas
warnings.filterwarnings('ignore', category=UserWarning, message=r'.*SQLAlchemy connectable.*')
warnings.filterwarnings('ignore', category=FutureWarning, message=r'.*ChainedAssignmentError.*')

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def process_cruce_datos(origen, test_insert=True):
    inicio = datetime.now()
    
    base_dir = os.path.dirname(__file__)
    excel_path = os.path.join(base_dir, "AF_Facturas.xlsx")
    output_path = os.path.join(base_dir, "Reporte_Fiscal_Historico.csv")
    logging.info(f"--- INICIANDO PROCESO DE HOMOLOGACIÓN Y REGISTRO CRM [{inicio.strftime('%Y-%m-%d %H:%M:%S')}] ---")

    try:
        # 1. Extraer datos de SQL Server (ETL)
        logging.info("Consultando datos de SQL Server (ETL)...")
        conn_sql, cursor_sql = Conexiones.connect_ETL_local_sql(origen)
        if not conn_sql: return
        
        sql_query = "SELECT Id, Name, VEC_ID_Empresa__c FROM Extraer_EmpresasU4O WHERE VEC_ID_Empresa__c IS NOT NULL"
        df_sql = pd.read_sql(sql_query, conn_sql)
        df_sql['Name'] = df_sql['Name'].astype(str).str.strip()

        # Lookup global Name(upper) -> IdEmpresa (Salesforce Account Id) para resolver
        # variantes que vengan de la tabla EmpresasHomologadas / Nombre del Receptor
        name_to_id_global = {}
        for _id, _n in zip(df_sql['Id'], df_sql['Name']):
            if pd.isna(_id) or pd.isna(_n):
                continue
            key = str(_n).strip().upper()
            if key and key not in name_to_id_global:
                name_to_id_global[key] = str(_id).strip()
        
        sql_homologadas = "SELECT [NombreOriginal], [NombrePrincipal] FROM [ETL].[dbo].[EmpresasHomologadas]"
        df_homo = pd.read_sql(sql_homologadas, conn_sql)
        
        cursor_sql.close()
        conn_sql.close()

        # Normalización Tier 1
        df_homo_clean = df_homo.dropna(subset=['NombreOriginal', 'NombrePrincipal']).copy()
        df_homo_clean['NombreOriginal'] = df_homo_clean['NombreOriginal'].astype(str).str.strip()
        df_homo_clean['NombrePrincipal'] = df_homo_clean['NombrePrincipal'].astype(str).str.strip()
        
        original_to_principal_upper = {row['NombreOriginal'].upper(): row['NombrePrincipal'] for _, row in df_homo_clean.iterrows()}
        
        principal_to_variants = {}
        for _, row in df_homo_clean.iterrows():
            p = row['NombrePrincipal']
            o = row['NombreOriginal']
            if p not in principal_to_variants: principal_to_variants[p] = set()
            principal_to_variants[p].add(o)
        
        principal_to_variants = {k: list(v) for k, v in principal_to_variants.items()}
        all_known_principals_upper = {p.upper() for p in principal_to_variants.keys()}

        # Homologación Tier 1
        df_sql['NombreHomologado'] = df_sql['Name'].apply(lambda x: original_to_principal_upper.get(str(x).strip().upper()))

        # 2. Extraer datos de Excel
        logging.info(f"Cargando archivo Excel: {excel_path}...")
        df_excel = pd.read_excel(excel_path)
        
        col_id_cli = 'ID Cliente'
        col_rfc = 'RFC receptor'
        col_nombre_rec = 'Nombre del Receptor'
        col_cp = [c for c in df_excel.columns if 'digoPostalR' in c or 'digoPostal' in c][0]
        col_regimen = [c for c in df_excel.columns if 'gimenFiscalR' in c or 'gimenFiscal' in c][0]
        col_fecha = [c for c in df_excel.columns if 'Fecha de emisi' in c or 'Fecha de emisin' in c][0]
        
        df_excel[col_fecha] = pd.to_datetime(df_excel[col_fecha], errors='coerce')

        # 3. Join
        logging.info("Ejecutando cruce de datos (Join)...")
        df_final = pd.merge(
            df_sql, 
            df_excel[[col_id_cli, col_rfc, col_nombre_rec, col_cp, col_regimen, col_fecha]], 
            left_on='VEC_ID_Empresa__c', 
            right_on=col_id_cli, 
            how='inner'
        )

        # 4. Consolidación: 1 fila por RFC receptor; CP, Régimen y Fecha como objetos JSON {Ultimo, Historico}
        logging.info("Consolidando perfiles fiscales (1 fila por RFC, histórico en JSON)...")
        df_final = df_final.sort_values(col_fecha, ascending=False).reset_index(drop=True)

        def _build_hist_obj(values_in_order):
            """Construye {Ultimo: <más reciente>, Historico: [únicos preservando orden]}.

            Asume `values_in_order` viene ordenado de más reciente a más antiguo.
            Normaliza floats enteros (601.0 -> "601") y descarta nulos / vacíos.
            """
            seen = set()
            historico = []
            for v in values_in_order:
                if v is None:
                    continue
                if isinstance(v, float) and pd.isna(v):
                    continue
                if isinstance(v, float) and v == int(v):
                    v = str(int(v))
                else:
                    v = str(v).strip()
                if not v:
                    continue
                if v not in seen:
                    seen.add(v)
                    historico.append(v)
            ultimo = historico[0] if historico else None
            return {"Ultimo": ultimo, "Historico": historico}

        consolidated = []
        for rfc, sub in df_final.groupby(col_rfc, sort=False):
            head = sub.iloc[0]  # más reciente (orden ya garantizado)
            cp_obj = _build_hist_obj(sub[col_cp].tolist())
            rf_obj = _build_hist_obj(sub[col_regimen].tolist())
            fechas = [d.strftime('%Y/%m/%d') if pd.notna(d) else None for d in sub[col_fecha]]
            fecha_obj = _build_hist_obj(fechas)

            # Preservar la homologación Tier 1 si algún registro histórico la tenía
            # (evita que la consolidación pierda el match cuando el registro más reciente no homologa)
            homol_existente = sub.loc[sub['NombreHomologado'].notna(), 'NombreHomologado']
            nombre_homologado = homol_existente.iloc[0] if not homol_existente.empty else head['NombreHomologado']

            # Names históricos asociados al RFC (para enriquecer Variantes en Validacion JSON)
            names_historicos = list(dict.fromkeys(
                sub['Name'].dropna().astype(str).str.strip().tolist()
            ))

            # Mapa Name(upper) -> IdEmpresa de los registros que se consolidaron en este RFC
            ids_by_name_local = {}
            for _, _r in sub.iterrows():
                if pd.isna(_r['Id']) or pd.isna(_r['Name']):
                    continue
                _key = str(_r['Name']).strip().upper()
                _val = str(_r['Id']).strip()
                if _key and _val:
                    ids_by_name_local.setdefault(_key, _val)

            consolidated.append({
                col_id_cli: head[col_id_cli],
                'Name': head['Name'],
                'NombreHomologado': nombre_homologado,
                col_rfc: rfc,
                col_nombre_rec: head[col_nombre_rec],
                'CodigoPostal': cp_obj,
                'RegimenFiscal': rf_obj,
                'FechaFacturacion': fecha_obj,
                '_NamesHistoricos': names_historicos,
                '_IdsByName': ids_by_name_local,
            })

        df_final = pd.DataFrame(consolidated)

        # 5. Tier 2 (SINDATA - Consulta)
        logging.info("Consultando SINDATA para Tier 2...")
        mask_missing = df_final['NombreHomologado'].isna()
        missing_names = df_final.loc[mask_missing, 'Name'].unique()
        
        if len(missing_names) > 0:
            try:
                conn_sin, cursor_sin = Conexiones.connect_SINDATA_saas_sql()
                if conn_sin:
                    sql_crm = "SELECT DISTINCT [EmpresaCRM_Nombre] FROM [SIN_Data].[dbo].[EmpresaCRM]"
                    df_crm = pd.read_sql(sql_crm, conn_sin)
                    crm_lookup = {str(n).strip().upper(): str(n).strip() for n in df_crm['EmpresaCRM_Nombre'].dropna()}

                    for name in missing_names:
                        name_upper = str(name).strip().upper()
                        if name_upper in crm_lookup:
                            df_final.loc[df_final['Name'] == name, 'NombreHomologado'] = crm_lookup[name_upper]
                    
                    cursor_sin.close()
                    conn_sin.close()
            except Exception as e_sin:
                logging.error(f"Error en Tier 2: {e_sin}")

        # 6. REGISTRO EN CRM (PROCESAMIENTO LOTE)
        if test_insert:
            logging.info("Buscando registros 'No Homologados' para inserción masiva...")
            unhomologated_names = df_final[df_final['NombreHomologado'].isna()]['Name'].unique()
            
            if len(unhomologated_names) > 0:
                try:
                    conn_sin, cursor_sin = Conexiones.connect_SINDATA_saas_sql()
                    if conn_sin:
                        # Obtener el ID inicial
                        cursor_sin.execute("SELECT MAX([EmpresaCRM_Id])+1 FROM [SIN_Data].[dbo].[EmpresaCRM]")
                        next_id = cursor_sin.fetchone()[0]
                        if next_id is None: next_id = 1
                        
                        now = datetime.now()
                        insert_query = """
                        INSERT INTO [SIN_Data].[dbo].[EmpresaCRM] 
                        VALUES (?, ?, NULL, NULL, 'Pendiente', ?, NULL, 'Oportunidades')
                        """
                        
                        inserted_count = 0
                        for target_name in unhomologated_names:
                            # Insertar empresa por empresa con su propio ID
                            cursor_sin.execute(insert_query, (next_id, str(target_name), now))
                            logging.info(f"✅ Registrando en CRM: {target_name} (ID: {next_id})")
                            
                            # Actualizar en df_final para el reporte actual
                            df_final.loc[df_final['Name'] == target_name, 'NombreHomologado'] = target_name
                            
                            next_id += 1
                            inserted_count += 1
                        
                        conn_sin.commit()
                        logging.info(f"--- INSERCIÓN FINALIZADA: {inserted_count} empresas registradas en CRM con estatus 'Pendiente' ---")
                        cursor_sin.close()
                        conn_sin.close()
                except Exception as e_ins:
                    logging.error(f"❌ Error al insertar en lote CRM: {e_ins}")

        # 7. Evidencia JSON
        def generate_evidencia(row):
            name_val = str(row['Name']).strip()
            name_upper = name_val.upper()
            receptor = str(row[col_nombre_rec]).strip() if pd.notna(row[col_nombre_rec]) else ""
            principal = row['NombreHomologado']
            item = {"EntradaReporte": name_val, "ValidaExistencia": "No", "NombrePrincipal": "" if pd.isna(principal) else str(principal), "Variantes": []}

            if name_upper in original_to_principal_upper:
                p_name = original_to_principal_upper[name_upper]
                item.update({"ValidaExistencia": "Sí", "NombrePrincipal": p_name, "Variantes": principal_to_variants.get(p_name, [])})
            elif name_upper in all_known_principals_upper:
                p_case = [k for k in principal_to_variants.keys() if k.upper() == name_upper][0]
                item.update({"ValidaExistencia": "Sí (Es Principal)", "NombrePrincipal": p_case, "Variantes": principal_to_variants.get(p_case, [])})
            elif principal and not pd.isna(principal):
                item["ValidaExistencia"] = "Sí (SINDATA/Match)"

            # Enriquecer variantes con Nombre del Receptor si difiere de Name y NombrePrincipal
            variantes_upper = {v.upper() for v in item["Variantes"]}
            np_upper = item["NombrePrincipal"].upper() if item["NombrePrincipal"] else ""

            if receptor and receptor.upper() not in {name_upper, np_upper, ""}:
                if receptor.upper() not in variantes_upper:
                    item["Variantes"].append(receptor)
                    variantes_upper.add(receptor.upper())

            # Enriquecer con Names históricos asociados al RFC (otros Salesforce Accounts que comparten RFC)
            for n in (row.get('_NamesHistoricos') or []):
                n_clean = str(n).strip()
                if not n_clean:
                    continue
                n_upper = n_clean.upper()
                if n_upper in {name_upper, np_upper} or n_upper in variantes_upper:
                    continue
                item["Variantes"].append(n_clean)
                variantes_upper.add(n_upper)

            # VariantesIdEmpresa: {nombre_variante: IdEmpresa} para cada variante que exista en SF
            ids_local = row.get('_IdsByName') or {}
            variantes_ids = {}
            # Empezar con el Name del registro (EntradaReporte)
            if name_val:
                _id = ids_local.get(name_upper) or name_to_id_global.get(name_upper)
                if _id:
                    variantes_ids[name_val] = _id
            # Luego cada variante del Validacion JSON
            for v in item["Variantes"]:
                v_clean = str(v).strip()
                if not v_clean or v_clean in variantes_ids:
                    continue
                v_upper = v_clean.upper()
                _id = ids_local.get(v_upper) or name_to_id_global.get(v_upper)
                if _id:
                    variantes_ids[v_clean] = _id

            return pd.Series({
                'Validacion JSON': json.dumps(item, ensure_ascii=False),
                'VariantesIdEmpresa': json.dumps(variantes_ids, ensure_ascii=False),
            })

        evidencia = df_final.apply(generate_evidencia, axis=1)
        df_final['Validacion JSON'] = evidencia['Validacion JSON']
        df_final['VariantesIdEmpresa'] = evidencia['VariantesIdEmpresa']

        # Serializar los objetos histórico a JSON string para CSV/SQL
        df_final['CodigoPostal'] = df_final['CodigoPostal'].apply(lambda x: json.dumps(x, ensure_ascii=False))
        df_final['RegimenFiscal'] = df_final['RegimenFiscal'].apply(lambda x: json.dumps(x, ensure_ascii=False))
        df_final['FechaFacturacion'] = df_final['FechaFacturacion'].apply(lambda x: json.dumps(x, ensure_ascii=False))
        df_final = df_final.drop(columns=['_NamesHistoricos', '_IdsByName'], errors='ignore')

        # 8. Guardado CSV (sin columna Id; los Ids viven dentro de VariantesIdEmpresa)
        columnas = [col_id_cli, 'Name', 'NombreHomologado', col_rfc, col_nombre_rec,
                    'CodigoPostal', 'RegimenFiscal', 'FechaFacturacion',
                    'Validacion JSON', 'VariantesIdEmpresa']
        df_final = df_final[columnas].sort_values(by=['Name'], ascending=[True])
        df_final.to_csv(output_path, index=False, encoding='utf-8-sig')
        logging.info(f"Guardado CSV: {output_path}")

        # 9. Guardado en tabla ETL: Reporte_FiscalHistorico
        logging.info("Insertando resultados en tabla [ETL].[dbo].[Reporte_FiscalHistorico]...")
        conn_etl, cursor_etl = Conexiones.connect_ETL_local_sql(origen)
        if conn_etl:
            try:
                # Asegurar esquema actualizado (idempotente):
                # - Renombrar 'Ultima Fecha Facturacion' -> 'FechaFacturacion' si aún existe
                # - Ampliar a NVARCHAR(MAX) para soportar JSON en CP/Régimen/Fecha
                # - Agregar columna VariantesIdEmpresa si no existe
                # - Eliminar columna [Id] si todavía existe (los Ids viven en VariantesIdEmpresa)
                cursor_etl.execute("""
                    IF EXISTS (
                        SELECT 1 FROM sys.columns
                        WHERE object_id = OBJECT_ID('dbo.Reporte_FiscalHistorico')
                          AND name = 'Ultima Fecha Facturacion'
                    )
                    BEGIN
                        EXEC sp_rename
                            @objname = N'dbo.Reporte_FiscalHistorico.[Ultima Fecha Facturacion]',
                            @newname = N'FechaFacturacion',
                            @objtype = N'COLUMN';
                    END
                """)
                for col_to_alter in ('CodigoPostal', 'RegimenFiscal', 'FechaFacturacion'):
                    cursor_etl.execute(
                        f"ALTER TABLE [dbo].[Reporte_FiscalHistorico] "
                        f"ALTER COLUMN [{col_to_alter}] NVARCHAR(MAX) NULL"
                    )
                cursor_etl.execute("""
                    IF NOT EXISTS (
                        SELECT 1 FROM sys.columns
                        WHERE object_id = OBJECT_ID('dbo.Reporte_FiscalHistorico')
                          AND name = 'VariantesIdEmpresa'
                    )
                    BEGIN
                        ALTER TABLE [dbo].[Reporte_FiscalHistorico] ADD [VariantesIdEmpresa] NVARCHAR(MAX) NULL
                    END
                """)
                cursor_etl.execute("""
                    IF EXISTS (
                        SELECT 1 FROM sys.columns
                        WHERE object_id = OBJECT_ID('dbo.Reporte_FiscalHistorico')
                          AND name = 'Id'
                    )
                    BEGIN
                        ALTER TABLE [dbo].[Reporte_FiscalHistorico] DROP COLUMN [Id]
                    END
                """)
                conn_etl.commit()

                cursor_etl.execute("TRUNCATE TABLE [dbo].[Reporte_FiscalHistorico]")

                df_insert = df_final.fillna('')
                insert_cols = ['ID Cliente', 'Name', 'NombreHomologado', 'RFC receptor', 'Nombre del Receptor',
                               'CodigoPostal', 'RegimenFiscal', 'FechaFacturacion',
                               'Validacion JSON', 'VariantesIdEmpresa']
                rows = [tuple(str(v) for v in row) for row in df_insert[insert_cols].itertuples(index=False, name=None)]

                # INSERT con nombres explícitos para no depender del orden físico de columnas
                col_list_sql = ', '.join(f'[{c}]' for c in insert_cols)
                placeholders = ','.join(['?'] * len(insert_cols))
                cursor_etl.executemany(
                    f"INSERT INTO [dbo].[Reporte_FiscalHistorico] ({col_list_sql}) VALUES ({placeholders})",
                    rows
                )
                conn_etl.commit()
                logging.info(f"✅ Insertados {len(rows)} registros en [Reporte_FiscalHistorico]")
            except Exception as e_etl:
                logging.error(f"❌ Error al guardar en tabla ETL: {e_etl}")
            finally:
                cursor_etl.close()
                conn_etl.close()

        logging.info(f"--- PROCESO FINALIZADO CON ÉXITO ---")

    except Exception as e:
        logging.error(f"Error general: {e}")

def main(origen):
    process_cruce_datos(origen, test_insert=True)

if __name__ == "__main__":
    import sys
    origen = sys.argv[1] if len(sys.argv) > 1 else None
    main(origen)
