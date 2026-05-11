import requests
from datetime import datetime, timedelta
import pandas as pd
import Conexiones
import sys

def get_latest_exchange_rate_from_db(connection, origin_currency, change_currency):
    query = """
        SELECT TipoCambio
        FROM Extraer_TipoCambio
        WHERE MonedaOrigen = ? AND MonedaCambio = ?
        ORDER BY Fecha DESC
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, (origin_currency, change_currency))
            row = cursor.fetchone()
            if row:
                return float(row[0])
    except Exception as e:
        print(f'Error fetching latest exchange rate from DB for {origin_currency}: {str(e)}')
    return None

def fetch_exchange_rate(currency_origin, current_date_yesterday, current_date):
    api_key = 'acde33d1d2e70e946b48b2235a7009ffa293899a72dd7d458ed2c02c3ef307fb'
    endpoint = ''
    if currency_origin == "USD":
        endpoint = f'https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF43718/datos/{current_date_yesterday}/{current_date}'
    elif currency_origin == "EUR":
        endpoint = f'https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF46410/datos/{current_date_yesterday}/{current_date}'

    params = {'token': api_key, 'mediaType': 'json'}
    try:
        response = requests.get(endpoint, params=params, timeout=15)
        if response.status_code == 200:
            data = response.json()
            exchange_rate = data['bmx']['series'][0]['datos'][0]['dato']
            return exchange_rate
        else:
            print(f'Error fetching exchange rate: {response.status_code}')
            return None
    except Exception as e:
        print(f'API error fetching {currency_origin} exchange rate: {str(e)}')
        return None

def update_exchange_records(connection, currency_origin, currency_change, exchange_rate, current_date):
    query = f"""
        DELETE FROM Extraer_TipoCambio WHERE Fecha = '{current_date}' AND MonedaOrigen = '{currency_origin}' AND MonedaCambio = '{currency_change}';
        INSERT INTO Extraer_TipoCambio (MonedaOrigen, MonedaCambio, Fecha, TipoCambio)
        VALUES ('{currency_origin}', '{currency_change}', '{current_date}', '{exchange_rate}');
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            connection.commit()
        print('Exchange records updated successfully.')
    except Exception as e:
        print(f'Error updating exchange records: {str(e)}')

# Function to fetch exchange rate from database
def find_tipo_internacional(connection, origin_currency, change_currency):
    query = """
        SELECT MonedaOrigen, MonedaCambio, Fecha, TipoCambio
        FROM Extraer_TipoCambio
        WHERE MonedaOrigen = ? AND MonedaCambio = ?
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(query, (origin_currency, change_currency))
            rows = cursor.fetchall()
            if len(rows) == 0:
                return None  # No rows returned from the query

            # Extract column names from cursor description
            columns = [column[0] for column in cursor.description]

            # Construct DataFrame directly from rows
            df = pd.DataFrame([list(row) for row in rows], columns=columns)
            return df
    except Exception as e:
        print(f'Error fetching exchange rate: {str(e)}')
        return None

# Function to update records in Extraer_OportunidadesU4O table
def update_tipocambio(connection,  exchange_df, currency_code):
    cursor = connection.cursor()
    cursor.execute(f"""SELECT COUNT(*) FROM Extraer_OportunidadesU4O WHERE CurrencyIsoCode = '{currency_code}'""")
    count_result = cursor.fetchone()[0]

    if count_result > 0:
        cursor.execute(f"""
            SELECT CurrencyIsoCode, Amount, CloseDate, Id
            FROM Extraer_OportunidadesU4O
            WHERE CurrencyIsoCode != 'MXN' AND CurrencyIsoCode = '{currency_code}'
        """)
        records = cursor.fetchall()

        for record in records:
            #print(record.Id)
            #print(record.Amount)
            currency_code = record.CurrencyIsoCode
            amount = float(record.Amount)
            CloseDate = record.CloseDate

            closest_date = exchange_df.loc[(exchange_df['Fecha'] - CloseDate).abs().idxmin(), 'Fecha']
            tipo_cambio = exchange_df.loc[exchange_df['Fecha'] == closest_date, 'TipoCambio'].iloc[0]
            new_amount = amount * tipo_cambio

            cursor.execute("""
                UPDATE Extraer_OportunidadesU4O
                SET Amount = ?, CurrencyIsoCode = 'MXN'
                WHERE Id = ?
            """, (new_amount, record.Id))
        connection.commit()


def update_null_amount_values(connection):
    try:
        # SQL query to update the Amount column
        query = """
            UPDATE Extraer_OportunidadesU4O
            SET Amount = 0
            WHERE Amount IS NULL
        """

        # Execute the query
        with connection.cursor() as cursor:
            cursor.execute(query)
            # Commit the transaction
            connection.commit()

        print("Null values in the Amount column have been updated to 0.")

    except Exception as e:
        print(f'Error updating null amount values: {str(e)}')


def main(origen, current_date):
    startTime = datetime.now()

    SaaS_SINDATA_conn = None
    SaaS_SINDATA_cursor = None
    local_ETL_conn = None
    local_ETL_cursor = None

    SaaS_SINDATA_conn, SaaS_SINDATA_cursor = Conexiones.connect_SINDATA_saas_sql()
    local_ETL_conn, local_ETL_cursor = Conexiones.connect_ETL_local_sql(origen)

    # Convert the string to a datetime object
    current_date_str = datetime.strptime(current_date, "%Y-%m-%d")
    # Subtract one day from the current date
    previous_date = current_date_str - timedelta(days=1)
    # Convert the result back to a string in the same format
    current_date_yesterday = previous_date.strftime("%Y-%m-%d")

    usd_to_mxn = fetch_exchange_rate('USD',  current_date_yesterday, current_date)
    if usd_to_mxn is None:
        print("API failed. Falling back to the latest USD exchange rate from DB...")
        usd_to_mxn = get_latest_exchange_rate_from_db(local_ETL_conn, 'USD', 'MXN')
        
    eur_to_mxn = fetch_exchange_rate('EUR', current_date_yesterday, current_date)
    if eur_to_mxn is None:
        print("API failed. Falling back to the latest EUR exchange rate from DB...")
        eur_to_mxn = get_latest_exchange_rate_from_db(local_ETL_conn, 'EUR', 'MXN')

    if usd_to_mxn is not None and eur_to_mxn is not None:
        update_exchange_records(SaaS_SINDATA_conn, 'USD', 'MXN', usd_to_mxn, current_date)
        update_exchange_records(SaaS_SINDATA_conn, 'EUR', 'MXN', eur_to_mxn, current_date)
        update_exchange_records(local_ETL_conn, 'USD', 'MXN', usd_to_mxn, current_date)
        update_exchange_records(local_ETL_conn, 'EUR', 'MXN', eur_to_mxn, current_date)

    else:
        print('Failed to fetch exchange rates both from API and DB. Check error messages for details.')

    # Fetch exchange rates
    df_usd_to_mxn = find_tipo_internacional(local_ETL_conn, 'USD', 'MXN')
    df_eur_to_mxn = find_tipo_internacional(local_ETL_conn, 'EUR', 'MXN')

    #Update null values in import
    update_null_amount_values(local_ETL_conn)

    # Update opportunities for USD and EUR
    if df_usd_to_mxn is not None:
        update_tipocambio(local_ETL_conn, df_usd_to_mxn, 'USD')
    if df_eur_to_mxn is not None:
        update_tipocambio(local_ETL_conn, df_eur_to_mxn, 'EUR')

    print('U4O_Integrar_LimpiezaImportes | Tiempo de ejecución :', datetime.now() - startTime)

    # Close all cursors
    SaaS_SINDATA_cursor.close()
    local_ETL_cursor.close()

if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:
        # Default run arguments or prompt user/fail gracefully if required arguments are not present
        # Assume main() might be called by an orchestrator like Airflow/Prefect
        print("Usage: python U4O_Integrar_LimpiezaImportes.py <origen> <current_date>")
        # We can pass fallback arguments here if we know them or we can just exit
        pass