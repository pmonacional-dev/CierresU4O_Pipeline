import pandas as pd
import json
import os
from rapidfuzz import fuzz, utils
import re

def search_brand_ecosystem():
    report_path = os.path.join(os.path.dirname(__file__), "Reporte_Fiscal_Historico.csv")

    if not os.path.exists(report_path):
        print(f"Error: No se encuentra el reporte en {report_path}")
        return

    print("\n--- BUSCADOR HÍBRIDO (NOMBRE / RFC) - VISIÓN 360° ---")
    df = pd.read_csv(report_path)

    # Columnas fiscales ahora son JSON {Ultimo, Historico} consolidadas por RFC
    col_cp = 'CodigoPostal'
    col_regimen = 'RegimenFiscal'
    col_fecha = 'FechaFacturacion' if 'FechaFacturacion' in df.columns else 'Ultima Fecha Facturacion'

    def parse_hist(val):
        """Parse JSON {Ultimo, Historico} con tolerancia a valores legacy planos."""
        if pd.isna(val) or val == '' or val is None:
            return {"Ultimo": None, "Historico": []}
        if isinstance(val, dict):
            return val
        try:
            obj = json.loads(val)
            if isinstance(obj, dict) and 'Ultimo' in obj:
                return obj
            return {"Ultimo": str(val), "Historico": [str(val)]}
        except Exception:
            return {"Ultimo": str(val), "Historico": [str(val)]}

    # Asegurar que RFC sea string para la búsqueda
    df['RFC receptor'] = df['RFC receptor'].astype(str).str.strip().str.upper()

    # Pre-construir índice de candidatos por grupo para búsqueda rápida
    search_index = []
    for nombre_h, group in df.groupby('NombreHomologado'):
        rfcs = group['RFC receptor'].unique()
        candidates = [nombre_h]
        candidate_labels = ["Nombre Homologado"]

        for json_val in group['Validacion JSON'].unique():
            try:
                data = json.loads(json_val)
                entrada = data.get("EntradaReporte", "")
                if entrada and entrada not in candidates:
                    candidates.append(entrada)
                    candidate_labels.append("Nombre Original (Entrada)")
                for var in data.get("Variantes", []):
                    if var not in candidates:
                        candidates.append(var)
                        candidate_labels.append(f"Variante ({var})")
            except: pass

        search_index.append({
            "nombre_h": nombre_h,
            "rfcs": rfcs,
            "candidates": candidates,
            "labels": candidate_labels
        })

    while True:
        query = input("\nIntroduce Nombre de Empresa o RFC (o 'salir'): ").strip()
        if query.lower() in ['salir', 'exit', 'q']: break
        if not query: continue

        query_upper = query.upper()

        matches = []
        for item in search_index:
            best_score = 0
            match_reason = ""

            # 1. Evaluar contra RFCs del grupo
            for rfc in item["rfcs"]:
                if query_upper == rfc:
                    best_score = 100
                    match_reason = f"RFC Exacto ({rfc})"
                    break
                elif query_upper in rfc:
                    score = (len(query_upper) / len(rfc)) * 90
                    if score > best_score:
                        best_score = score
                        match_reason = f"RFC Parcial ({rfc})"

            # 2. Evaluar contra todos los candidatos con WRatio
            if best_score < 100:
                for cand, label in zip(item["candidates"], item["labels"]):
                    score = fuzz.WRatio(query, cand, processor=utils.default_process)
                    if score > best_score:
                        best_score = score
                        match_reason = label

            if best_score >= 40:
                matches.append({
                    "Nombre": item["nombre_h"],
                    "Score": best_score,
                    "Reason": match_reason,
                    "RFCs": item["rfcs"]
                })

        # Ordenar por Score - top 10
        matches = sorted(matches, key=lambda x: x['Score'], reverse=True)[:10]

        if not matches:
            print("No se encontraron coincidencias significativas.")
            continue

        # --- PASO 1: Mostrar 10 sugerencias y permitir selección múltiple ---
        print("\nSugerencias encontradas:")
        for i, m in enumerate(matches, 1):
            print(f"  {i}. [{int(m['Score'])}%] {m['Nombre']} - Vía: {m['Reason']}")

        print("\n  Selecciona empresas (números separados por coma, ej: 1,3,5)")
        print("  Enter sin valor = nueva búsqueda")
        empresas_elegidas = []

        while True:
            sel = input("  > ").strip()
            if not sel:
                break
            try:
                indices = [int(x.strip()) for x in sel.split(",")]
                for idx in indices:
                    if 1 <= idx <= len(matches):
                        elegida = matches[idx - 1]
                        if elegida["Nombre"] not in [e["Nombre"] for e in empresas_elegidas]:
                            empresas_elegidas.append(elegida)
                            print(f"    + {elegida['Nombre']}")
                        else:
                            print(f"    (ya seleccionada: {elegida['Nombre']})")
                    else:
                        print(f"    Número {idx} fuera de rango.")
            except ValueError:
                print("    Entrada no válida. Usa números separados por coma.")
                continue

            print(f"\n  Seleccionadas: {len(empresas_elegidas)} empresa(s). ¿Agregar más? (números o Enter para continuar)")

        if not empresas_elegidas:
            continue

        # --- PASO 2: Mostrar empresas elegidas con sus razones sociales ---
        print(f"\n{'='*80}")
        print("EMPRESAS SELECCIONADAS Y SUS RAZONES SOCIALES")
        print(f"{'='*80}")

        razones_sociales = []
        for emp in empresas_elegidas:
            ecosistema = df[df['NombreHomologado'] == emp['Nombre']].copy()
            # Cada fila ya está consolidada por RFC; solo extraer Último (con histórico para mostrar variantes)
            ecosistema['_cp'] = ecosistema[col_cp].apply(parse_hist)
            ecosistema['_rf'] = ecosistema[col_regimen].apply(parse_hist)
            ecosistema['_fecha'] = ecosistema[col_fecha].apply(parse_hist)

            print(f"\n  [{emp['Nombre']}]")
            for _, row in ecosistema.iterrows():
                cp_ultimo = row['_cp'].get('Ultimo') or ''
                rf_obj = row['_rf']
                rf_hist = rf_obj.get('Historico') or []
                rf_display = ', '.join(rf_hist) if len(rf_hist) > 1 else (rf_obj.get('Ultimo') or '')
                fecha_ultimo = row['_fecha'].get('Ultimo') or ''
                razones_sociales.append({
                    "empresa": emp["Nombre"],
                    "rfc": row["RFC receptor"],
                    "razon_social": row["Nombre del Receptor"],
                    "cp": cp_ultimo,
                    "regimen": rf_display,
                    "ultima_factura": fecha_ultimo
                })
                print(f"    RFC: {row['RFC receptor']} | {row['Nombre del Receptor']} | CP: {cp_ultimo} | Régimen: {rf_display} | Última fact: {fecha_ultimo}")

        # --- PASO 3: Confirmar ---
        print(f"\n  Total: {len(razones_sociales)} razón(es) social(es) de {len(empresas_elegidas)} empresa(s)")
        confirma = input("  ¿Continuar a selección de razones sociales? (s/n): ").strip().lower()
        if confirma not in ['s', 'si', 'sí', 'y', 'yes', '']:
            print("  Cancelado. Volviendo al buscador...")
            continue

        # --- PASO 4: Selección de razones sociales para facturar ---
        print(f"\n{'='*80}")
        print("SELECCIÓN DE RAZONES SOCIALES PARA FACTURAR")
        print(f"{'='*80}\n")

        for i, rs in enumerate(razones_sociales, 1):
            print(f"  {i}. {rs['razon_social']}  |  RFC: {rs['rfc']}  |  [{rs['empresa']}]")

        print(f"\n  Selecciona razones sociales (números separados por coma, ej: 1,3)")
        print("  'todas' = seleccionar todas  |  Enter sin valor = cancelar")
        seleccionadas = []

        while True:
            sel = input("  > ").strip()
            if not sel:
                break
            if sel.lower() in ['todas', 'all', '*']:
                seleccionadas = list(range(len(razones_sociales)))
                print(f"    + Todas seleccionadas ({len(razones_sociales)})")
            else:
                try:
                    indices = [int(x.strip()) for x in sel.split(",")]
                    for idx in indices:
                        if 1 <= idx <= len(razones_sociales):
                            if (idx - 1) not in seleccionadas:
                                seleccionadas.append(idx - 1)
                                rs = razones_sociales[idx - 1]
                                print(f"    + {rs['razon_social']} ({rs['rfc']})")
                            else:
                                print(f"    (ya seleccionada: {razones_sociales[idx-1]['razon_social']})")
                        else:
                            print(f"    Número {idx} fuera de rango.")
                except ValueError:
                    print("    Entrada no válida. Usa números separados por coma.")
                    continue

            print(f"\n  Seleccionadas: {len(seleccionadas)} razón(es). ¿Agregar más? (números o Enter para generar JSON)")

        if not seleccionadas:
            print("  Sin selección. Volviendo al buscador...")
            continue

        # --- PASO 5: Generar JSON ---
        resultado = [
            {"empresa": razones_sociales[i]["razon_social"], "rfc": razones_sociales[i]["rfc"]}
            for i in seleccionadas
        ]

        json_output = json.dumps(resultado, indent=2, ensure_ascii=False)
        print(f"\n{'='*80}")
        print("JSON GENERADO")
        print(f"{'='*80}")
        print(json_output)

        # Guardar a archivo
        output_path = os.path.join(os.path.dirname(__file__), "Seleccion_Facturacion.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(json_output)
        print(f"\nGuardado en: {output_path}")

if __name__ == "__main__":
    search_brand_ecosystem()
