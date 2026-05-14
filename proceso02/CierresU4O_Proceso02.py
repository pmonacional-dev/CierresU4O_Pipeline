# -*- coding: utf-8 -*-
"""
Created on Sat Apr  5 10:25:22 2025

@author: L03523797
"""

from Insert_EnviosCerradasGanadas import main as main_envios
from Insert_Datos_CRM import main as main_datos_crm
from Update_Datos_CRM import main as main_update_crm
#from Calcula_importe_gestionado_old import main as main_importe
from Calcula_importe_gestionado import main as main_importe
from Update_Datos_CRM_From_SF import main as main_update_from_sf
from actualizaWinroom_PBI import main as main_winroom
from Export_Reporte_TLG import main as main_reporte_tlg
from ETL_Formato_Universal import main as main_formato_universal

def ejecutar_flujos(origen=None, anio_meta=None):
    import os
    if os.getenv("U4O_DRY_RUN", "0") == "1":
        import dryrun  # noqa: F401 — activa el modo prueba antes de cualquier conexión
    if origen is None:
        origen = os.getenv("U4O_ORIGEN", "Antonio")
    if anio_meta is None:
        anio_meta = os.getenv("U4O_ANIO_META", "2025-2026")
    
    print("Iniciando ejecución de flujos...")

    print("1. Insert_EnviosCerradasGanadas")
    main_envios()

    print("2. Insert_Datos_CRM")
    main_datos_crm()

    print("3. Update_Datos_CRM")
    main_update_crm()
    main_update_from_sf()

    print("4. Fix WinRoom ImagenFunnel PBI (Cerrada Ganada año anterior)")
    main_winroom()

    print("5. Calcula_importe_gestionado para el dashboard del PHub")
    main_importe()

    print("6. Export_Reporte_TLG (Excel diario)")
    main_reporte_tlg(origen=origen, anio_meta=anio_meta)

    print("7. ETL_Formato_Universal")
    main_formato_universal()

    print("Ejecución completa.")

if __name__ == "__main__":
    import os
    _origen = os.getenv("U4O_ORIGEN", "Antonio")
    _anio_meta = os.getenv("U4O_ANIO_META", "2025-2026")
    ejecutar_flujos(_origen, _anio_meta)
