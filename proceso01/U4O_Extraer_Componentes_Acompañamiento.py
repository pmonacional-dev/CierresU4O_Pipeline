import unicodedata
from datetime import datetime
from simple_salesforce.exceptions import SalesforceMalformedRequest
import pyodbc
from decimal import Decimal
import Conexiones


def normalizeDate(datestring):
    if datestring is not None:
        try:
            if len(str(datestring)) == 13:
                datestring = str(datestring)
                datestring = datestring[:-3]
                datestring = datetime.fromtimestamp(int(datestring))
                datestring = str(datestring)
            else:
                datestring = datetime.strptime(datestring[:-9], '%Y-%m-%dT%H:%M:%S')
                datestring = str(datestring)
        except (TypeError, NameError):
            pass
    return datestring


def main(origen):
    startTime = datetime.now()
    
    # 1. Conexiones a Base de Datos
    sf = Conexiones.connect_SF(origen)
    conn_sql_server, sql_cursor = Conexiones.connect_ETL_local_sql(origen)
    
    print("Limpiando tabla de historial de Acompañamiento...")
    try:
        # Solo limpiamos la tabla de porcentajes de Acompañamiento
        sql_cursor.execute("DELETE FROM Extraer_Acompañamiento_Porcentaje")
        sql_cursor.commit()
    except Exception as e:
        print("Advertencia al limpiar tabla (puede que no exista): {}".format(str(e)))
    
    # 2. Campos necesarios
    fields = [
        'Id',
        'VEC_Modalidad_1__c',
        'VEC_Modalidad_2__c',
        'VEC_ModalidadTres__c',
        'VEC_ModalidadCuatro__c',
        'VEC_ModalidadCinco__c',
        'VEC_Modalidad_1_1__c',
        'VEC_Modalidad_2_2__c',
        'VEC_PorcentajeModalidadTres__c',
        'VEC_PorcentajeModalidadCuatro__c',
        'VEC_PorcentajeModalidadCinco__c',
        'VEC_Coordinador_academico1__c',
        'VEC_Desarrollador_de_solucion__c'
        ]
    
    print("Obtener lista de oportunidades con Acompañamiento desde CRM...")
    try:
        # 3. Query SOQL Específico para Acompañamiento
        query = """
            SELECT {} FROM Opportunity
            WHERE
            (
                IsDeleted = False
                AND StageName IN ('Cerrada Ganada','Cerrada Perdida', 'Oportunidad','Propuesta','Negociación')
                AND RecordTypeId IN ('01241000001EgMRAA0','01241000001EgMSAA0','01241000001EgMTAA0')
                AND
                (
                    (VEC_Modalidad_1__c = 'Acompañamiento' OR VEC_Modalidad_2__c = 'Acompañamiento'
                     OR VEC_ModalidadTres__c = 'Acompañamiento' OR VEC_ModalidadCuatro__c = 'Acompañamiento'
                     OR VEC_ModalidadCinco__c = 'Acompañamiento')
                    OR (VEC_Coordinador_academico1__c = '0033f00000DGndzAAD')
                    OR (VEC_Desarrollador_de_solucion__c = '0033f00000DGndzAAD')
                )
            )
           """.format(','.join(fields)).encode('utf-8')
        
        resultTask = sf.bulk.Opportunity.query(query)
        total_records = len(resultTask)
        print(f"Total de registros de Acompañamiento encontrados: {total_records}")
        
        # 4. Obtener Importes Base desde SQL Server (Extraer_OportunidadesU4O)
        opportunity_ids = [record['Id'] for record in resultTask]
        
        result_opportunidades_u4o = []
        if opportunity_ids:
            opportunity_ids_str = ",".join(["'{}'".format(opp_id) for opp_id in opportunity_ids])
            select_query = f"SELECT Id, Amount FROM Extraer_OportunidadesU4O WHERE Id IN ({opportunity_ids_str})"
            
            try:
                sql_cursor.execute(select_query)
                result_opportunidades_u4o = sql_cursor.fetchall()
            except pyodbc.Error as e:
                print("Error consultando importes base: {}".format(str(e)))
        
        # 5. Procesamiento de Cálculos
        opportunity_data_acom = []
        
        for record in resultTask:
            opportunity_id = record['Id']
            
            # Obtener monto base de la BD local
            base_amount = next((row.Amount for row in result_opportunidades_u4o if row.Id == opportunity_id), None)
            if base_amount is None:
                base_amount = 0
            
            # --- ASIGNACIÓN DE VARIABLES EXPLÍCITA (SOLICITUD DE USUARIO) ---
            # Extraemos las modalidades
            opportunity_Modalidad_1 = record['VEC_Modalidad_1__c']
            opportunity_Modalidad_2 = record['VEC_Modalidad_2__c']
            opportunity_Modalidad_3 = record['VEC_ModalidadTres__c']
            opportunity_Modalidad_4 = record['VEC_ModalidadCuatro__c']
            opportunity_Modalidad_5 = record['VEC_ModalidadCinco__c']
            
            # Extraemos los porcentajes tal como se solicitó
            opportunity_PorcentajeModalidad_1 = record['VEC_Modalidad_1_1__c']
            opportunity_PorcentajeModalidad_2 = record['VEC_Modalidad_2_2__c']
            opportunity_PorcentajeModalidad_3 = record['VEC_PorcentajeModalidadTres__c']
            opportunity_PorcentajeModalidad_4 = record['VEC_PorcentajeModalidadCuatro__c']
            opportunity_PorcentajeModalidad_5 = record['VEC_PorcentajeModalidadCinco__c']
            
            Acom_Amount = 0
            Acom_Percentage = "0"
            
            # Helper interno para calcular
            def calcular_modalidad(nombre_mod, porc_str, current_pct, current_amt):
                if nombre_mod == "Acompañamiento":
                    if porc_str is None:
                        porc_str = "100"
                    try:
                        # Convertir porcentaje "80%" o "80" a float 0.80
                        percentage_val = float(porc_str.strip('%')) / 100.0
                        
                        # Calcular monto: Base * Porcentaje
                        monto_calculado = float(base_amount) * percentage_val
                        
                        return porc_str, current_amt + monto_calculado
                    except ValueError:
                        print(f"Error convirtiendo porcentaje en ID: {opportunity_id}")
                return current_pct, current_amt
            
            # Lista de pares usando las variables extraídas arriba
            mod_pairs = [
                (opportunity_Modalidad_1, opportunity_PorcentajeModalidad_1),
                (opportunity_Modalidad_2, opportunity_PorcentajeModalidad_2),
                (opportunity_Modalidad_3, opportunity_PorcentajeModalidad_3),
                (opportunity_Modalidad_4, opportunity_PorcentajeModalidad_4),
                (opportunity_Modalidad_5, opportunity_PorcentajeModalidad_5)
                ]
            
            # Iterar y sumar importes si aparece Acompañamiento
            for mod, porc in mod_pairs:
                Acom_Percentage, Acom_Amount = calcular_modalidad(mod, porc, Acom_Percentage, Acom_Amount)
            
            # Validar condición especial de IDs (Coordinador/Desarrollador)
            # Si tiene los IDs, se considera Acompañamiento (True) aunque el monto calculado sea 0
            has_special_id = (record.get('VEC_Coordinador_academico1__c') == '0033f00000DGndzAAD' or
                              record.get('VEC_Desarrollador_de_solucion__c') == '0033f00000DGndzAAD')
            
            # Solo agregamos a la lista si hay monto calculado O si cumple la condición de IDs
            if Acom_Amount > 0 or has_special_id:
                # Calcular el importe que NO corresponde a acompañamiento (Non_Amount)
                Non_Amount = float(base_amount) - float(Acom_Amount)
                
                opportunity_data_acom.append({
                    'Id': opportunity_id,
                    'Non_Amount': Decimal(Non_Amount),
                    'Amount': Decimal(Acom_Amount),
                    'Percentage': Acom_Percentage
                    })
        
        # 6. Inserción en Base de Datos
        if opportunity_data_acom:
            print(f"Insertando {len(opportunity_data_acom)} registros...")
            # Estructura de tabla: Id, Non_Amount, Amount, Percentage
            insert_query = "INSERT INTO Extraer_Acompañamiento_Porcentaje (Id, Non_Amount, Amount, Percentage) VALUES (?, ?, ?, ?)"
            
            data_to_insert = [
                (str(data['Id']), float(data['Non_Amount']), float(data['Amount']), str(data['Percentage']))
                for data in opportunity_data_acom
                ]
            
            try:
                sql_cursor.executemany(insert_query, data_to_insert)
                sql_cursor.commit()
                print("Inserción exitosa.")
            except Exception as e:
                print(f"Error insertando datos: {str(e)}")
        else:
            print("No se encontraron oportunidades con componente de Acompañamiento para insertar.")
    
    except SalesforceMalformedRequest as e:
        print("Solicitud Salesforce mal formada: {}".format(str(e)))
    
    finally:
        if sql_cursor:
            sql_cursor.close()
            conn_sql_server.close()


if __name__ == "__main__":
    main(None)