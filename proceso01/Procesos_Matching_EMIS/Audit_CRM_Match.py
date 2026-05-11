"""
Auditoría puntual del catálogo CRM para un término.

DOCUMENTACIÓN COMPLETA: Manual_Usuario_Matching_EMIS.md (en esta carpeta).

Dado un término (ej. 'Furukawa'), muestra qué hay en
[ETL].[dbo].[Extraer_EmpresasU4O] y [ETL].[dbo].[EmpresasHomologadas],
y cómo se construye el grupo de NombrePrincipal con sus IdsCRM en el
sub-proceso CRM (Paso 2 del pipeline).

Uso:
    python Audit_CRM_Match.py --origen Erik --term Furukawa

Útil para entender por qué un DUNS terminó con N IdsCRM (a veces solo 1)
cuando visualmente parecía haber más cuentas — típicamente el motivo es
que las variantes esperadas no existen como Name exacto en
Extraer_EmpresasU4O o no están mapeadas en EmpresasHomologadas.

Solo lectura: NO modifica el Excel ni hace INSERT/UPDATE en SQL.
"""

import argparse
import json
import os
import sys
import warnings
from collections import defaultdict

warnings.filterwarnings('ignore', category=UserWarning,
                        message=r'.*SQLAlchemy connectable.*')
warnings.filterwarnings('ignore', category=FutureWarning,
                        message=r'.*ChainedAssignmentError.*')

import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import Conexiones


def audit(term: str, origen: str):
    print(f"\nConectando a [ETL] (origen='{origen}')...")
    conn, cursor = Conexiones.connect_ETL_local_sql(origen)
    if conn is None:
        raise RuntimeError(f"connect_ETL_local_sql('{origen}') retornó None.")

    try:
        like = f"%{term}%"

        # 1) Extraer_EmpresasU4O — cuentas SF que contienen el término
        print(f"\n{'='*70}")
        print(f"1. [ETL].[dbo].[Extraer_EmpresasU4O] WHERE Name LIKE '%{term}%'")
        print(f"   (sub-proceso CRM ya NO filtra por VEC_ID; se muestra solo informativo)")
        print(f"{'='*70}")
        df_sf = pd.read_sql(
            "SELECT Id, Name, VEC_ID_Empresa__c "
            "FROM [ETL].[dbo].[Extraer_EmpresasU4O] "
            "WHERE Name LIKE ?",
            conn, params=[like],
        )
        print(f"Filas: {len(df_sf)}")
        if len(df_sf) > 0:
            print(f"  Con VEC_ID_Empresa__c NOT NULL: {df_sf['VEC_ID_Empresa__c'].notna().sum()}")
            print(f"  Con VEC_ID_Empresa__c NULL:     {df_sf['VEC_ID_Empresa__c'].isna().sum()}")
            print()
            for _, r in df_sf.iterrows():
                vec = r['VEC_ID_Empresa__c'] if pd.notna(r['VEC_ID_Empresa__c']) else "NULL"
                print(f"  Id={r['Id']:<22}  VEC={vec!s:<14}  Name='{r['Name']}'")

        # 2) EmpresasHomologadas — variantes que contienen el término
        print(f"\n{'='*70}")
        print(f"2. [ETL].[dbo].[EmpresasHomologadas]")
        print(f"   WHERE NombreOriginal LIKE '%{term}%' OR NombrePrincipal LIKE '%{term}%'")
        print(f"{'='*70}")
        df_h = pd.read_sql(
            "SELECT NombreOriginal, NombrePrincipal "
            "FROM [ETL].[dbo].[EmpresasHomologadas] "
            "WHERE NombreOriginal LIKE ? OR NombrePrincipal LIKE ?",
            conn, params=[like, like],
        )
        print(f"Filas: {len(df_h)}")
        if len(df_h) > 0:
            for _, r in df_h.iterrows():
                print(f"  Original='{r['NombreOriginal']}'  →  Principal='{r['NombrePrincipal']}'")

        # 3) Reconstrucción del grupo igual que build_crm_catalog
        print(f"\n{'='*70}")
        print(f"3. RECONSTRUCCIÓN DEL GRUPO (lógica de build_crm_catalog)")
        print(f"{'='*70}")

        # Lookup Name(upper) → lista de Ids. El sub-proceso CRM ya NO filtra por VEC_ID
        # y preserva todos los Ids cuando varios SF Accounts comparten Name.
        df_sf_norm = df_sf.copy()
        df_sf_norm.loc[:, "Name"] = df_sf_norm["Name"].astype(str).str.strip()
        name_to_ids_local = defaultdict(list)
        for _id, _n in zip(df_sf_norm["Id"], df_sf_norm["Name"]):
            key = str(_n).strip().upper()
            _id_str = str(_id).strip()
            if key and _id_str and _id_str not in name_to_ids_local[key]:
                name_to_ids_local[key].append(_id_str)

        # Agrupar por NombrePrincipal (igual que el catálogo)
        df_h_clean = df_h.dropna(subset=["NombreOriginal", "NombrePrincipal"]).copy()
        df_h_clean.loc[:, "NombreOriginal"] = df_h_clean["NombreOriginal"].astype(str).str.strip()
        df_h_clean.loc[:, "NombrePrincipal"] = df_h_clean["NombrePrincipal"].astype(str).str.strip()

        principal_to_variants = defaultdict(set)
        for _, row in df_h_clean.iterrows():
            principal_to_variants[row["NombrePrincipal"]].add(row["NombreOriginal"])
            principal_to_variants[row["NombrePrincipal"]].add(row["NombrePrincipal"])

        # Cobertura: Name SF que no esté en EmpresasHomologadas → principal sintético
        original_uppers = {row["NombreOriginal"].upper() for _, row in df_h_clean.iterrows()}
        principal_uppers = {row["NombrePrincipal"].upper() for _, row in df_h_clean.iterrows()}
        for name in df_sf_norm["Name"].dropna().unique():
            n = str(name).strip()
            n_up = n.upper()
            if n_up not in original_uppers and n_up not in principal_uppers:
                principal_to_variants[n].add(n)

        # Resolver IdsCRM por principal y reportar por qué cada variante tiene/no tiene Id
        for principal, variantes_set in principal_to_variants.items():
            print(f"\nNombrePrincipal: '{principal}'")
            print(f"  Variantes ({len(variantes_set)}):")
            ids_resueltos = []
            seen_resueltos = set()
            for v in sorted(variantes_set):
                v_up = v.strip().upper()
                ids_v = name_to_ids_local.get(v_up, [])
                if ids_v:
                    estado = f"✓ resuelve a {len(ids_v)} Id(s): {ids_v}"
                    for _id in ids_v:
                        if _id not in seen_resueltos:
                            ids_resueltos.append(_id)
                            seen_resueltos.add(_id)
                else:
                    estado = "✗ no existe ningún Name='...' (case-insensitive) en Extraer_EmpresasU4O"
                print(f"    - '{v}'  →  {estado}")
            print(f"  IdsCRM finales para este principal: {ids_resueltos}")

        # 4) Resumen
        print(f"\n{'='*70}")
        print(f"4. RESUMEN DE COBERTURA")
        print(f"{'='*70}")
        total_sf = len(df_sf)
        total_principales = len(principal_to_variants)
        ids_unicos = set()
        for vs in principal_to_variants.values():
            for v in vs:
                for _id in name_to_ids_local.get(v.strip().upper(), []):
                    ids_unicos.add(_id)
        print(f"  Cuentas SF con '{term}' en el Name:                    {total_sf}")
        print(f"  (todas entran al catálogo — sin filtro VEC_ID)")
        print(f"  NombresPrincipales generados en el catálogo:           {total_principales}")
        print(f"  IdsCRM únicos resueltos en total:                      {len(ids_unicos)}")

    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Auditoría de un término en el catálogo CRM.")
    parser.add_argument("--origen", type=str, required=True,
                        help="'Erik' o 'Antonio' para connect_ETL_local_sql.")
    parser.add_argument("--term", type=str, required=True,
                        help="Término a buscar (LIKE %%term%% en Name / NombreOriginal / NombrePrincipal).")
    args = parser.parse_args()
    audit(args.term, args.origen)


if __name__ == "__main__":
    main()
