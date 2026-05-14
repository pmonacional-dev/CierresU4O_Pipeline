from datetime import datetime, timedelta
import concurrent.futures
import logging

from Conexiones_Startup import main as run_main_00
from U4O_Extraer_Oportunidades import main as run_main_01
from U4O_Integrar_LimpiezaImportes import main as run_main_02
from U4O_Extraer_TLG_U4P import main as run_main_03
from U4O_Extraer_Componentes_TLG import main as run_main_04
from U4O_Extraer_Posgrados import main as run_main_05
from U4O_Centralizar_ETL import main as run_main_06
from U4O_Centralizar_TLG import main as run_main_07
from U4O_Centralizar_SINDATA import main as run_main_08
from U4O_Centralizar_PASE import main as run_main_09
from U4O_Extraer_Actividades_DentroOportunidades import main as run_main_10

from U4O_Extraer_Empresas import main as run_main_11
from U4O_Extraer_Contactos import main as run_main_12
from U4O_Integrar_MapeoActividad import main as run_main_13
from U4O_Extraer_Componentes_IPortafolio import main as run_main_14
from U4O_Centralizar_IPortafolio import main as run_main_15
from U4O_Integrar_AvanceSeniority import main as run_main_16
from U4O_Centralizar_Inteligencia import main as run_main_17
from PMO_Documentos_Cierre import main as run_main_18
from PMO_Documentos_Actualiza import main as run_main_19
from U4O_Extraer_Componentes_Acompañamiento import main as run_main_20
from U4O_Centralizar_Acompañamiento import main as run_main_21
from U4O_Extraer_Actividades_FueraOportunidades import main as run_main_22
from Proceso_Fiscal.U4O_Limpieza_Fiscal import main as run_main_23
from Proceso_CambioFechaOportunidad.U4O_Monitoreo_FechasProyecto import main as run_main_24
from Procesos_Matching_EMIS.U4O_Matching_EMIS_Fiscal import main as run_main_25



def get_last_friday_date(current_date):
    current_date = datetime.now()
    days_until_friday = (current_date.weekday() - 4) % 7
    last_friday = current_date - timedelta(days=days_until_friday)
    return last_friday


def start_db_parallel(databases):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_results = {db: executor.submit(run_main_00, db) for db in databases}
        results = {db: future.result() for db, future in future_results.items()}
    return results


def main(origen=None, periodo=None, fechacambio=None):
    import os
    if os.getenv("U4O_DRY_RUN", "0") == "1":
        import dryrun  # noqa: F401 — activa el modo prueba antes de cualquier conexión
    if origen is None:
        origen = os.getenv("U4O_ORIGEN", "Erik")
    if periodo is None:
        periodo = os.getenv("U4O_PERIODO", "Semanal")
    if fechacambio is None:
        fechacambio = os.getenv("U4O_FECHACAMBIO", get_last_friday_date(datetime.now()).strftime("%Y-%m-%d"))

    start_time = datetime.now()
    print("Iniciando proceso...")
    logging.info('CierresU4O_Proceso01 | Inicia ejecución')

    databases = ["INTELIGENCIA", "PASE", "QLIK"]
    results = start_db_parallel(databases)

    if all(results.values()):
        print("Bases de datos en SaaS detectadas correctamente")

        if os.getenv("U4O_AUTO_CONFIRM", "0") == "1":
            response = "yes"
        else:
            response = input("¿Desea continuar con el proceso de cierre? (yes/no): ").lower()
        if response in ["yes", "y", "si", "sí", "s"]:
            print("Continuando el proceso de cierre...")
            
            # Common tasks for both "Diario" and "Semanal"
            if periodo in ["Diario", "Semanal"]:
                
                run_main_01(origen)  # U4O_Extraer_Oportunidades
                run_main_02(origen, fechacambio)  # U4O_Integrar_LimpiezaImportes
                run_main_12(origen)  # U4O_Extraer_Contactos
                run_main_10(origen)  # U4O_Extraer_Actividades_DentroOportunidades
                run_main_22(origen)  # U4O_Extraer_Actividades_FueraOportunidades
                run_main_11(origen)  # U4O_Extraer_Empresas
                run_main_18(origen)  # PMO_Documentos_Ganados
                run_main_19(origen)  # PMO_Documentos_Actualiza
                run_main_13(origen)  # U4O_Integrar_MapeoActividad de empresas (Genera el documento ActividadRecompra_U4O.csv y Reporte_AnalisisAtencionU4O )
                run_main_14(origen)  # U4O_Extraer_Oportunidades IPortafolio
                run_main_15(origen)  # U4O_Centralizar_IPortafolio
                run_main_03(origen)  # U4O_Extraer_TLG_U4P
                run_main_04(origen)  # U4O_Extraer_Componentes_TLG
                run_main_20(origen)  # U4O_Extraer_Componentes_Acompañamiento
                run_main_23(origen)  # Proceso_Fiscal: U4O_Limpieza_Fiscal (Registro en ETL)
                run_main_25(origen, periodo)  # Proceso_EMIS: Diario solo procesa pendientes; Semanal reválida todos lo Facturado=False contra catálogo CRM
                run_main_06(origen)  # U4O_Centralizar_ETL
                run_main_07(origen)  # U4O_Centralizar_TLG
                run_main_17(origen, periodo)  # U4O_Centralizar_Inteligencia
                run_main_21(origen)  # U4O_Centralizar_Acompañamiento
                run_main_08(periodo)  # U4O_Centralizar_SINDATA
                run_main_16(periodo)  # U4O_Integrar_AvanceSeniority
                run_main_09(periodo)  # U4O_Centralizar_PASE
                run_main_24(origen)  # Proceso_CambioFechaOportunidad: U4O_Monitoreo_FechasProyecto (Registro de cambio de fechas de inicio y termino)
                # run_main_22(origen) # U4O_Centralizar_PHub
                # run_main_05(origen) # U4O_Extraer_Posgrados

            elif periodo in ["Mensual1", "Mensual2"]:
                # U4O_Centralizar_PASE
                # Mensual1: Cierre mensual posterior al paso 1 para integrar las variantes de empresas para limpieza
                # Mensual2: Cierre mensual posterior al paso 2 para integrar los indicadores hacia el tablero de Inteligencia para expertos de EC
                run_main_09(periodo)
        
        elif response in ["no", "n"]:
            print("Deteniendo el proceso de cierre...")
    else:
        print("No se detectó actividad en todas las bases de datos en SaaS")
    
    logging.info(f'CierresU4O_Proceso01 | Tiempo de ejecución: {datetime.now() - start_time}')


if __name__ == "__main__":
    import os
    _origen = os.getenv("U4O_ORIGEN", "Erik")
    _periodo = os.getenv("U4O_PERIODO", "Semanal")
    _fechacambio = os.getenv("U4O_FECHACAMBIO", get_last_friday_date(datetime.now()).strftime("%Y-%m-%d"))
    main(_origen, _periodo, _fechacambio)