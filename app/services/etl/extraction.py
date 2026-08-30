import io

import pandas as pd
import requests

from app.utils.bcrp import _a_timestamp, _empalmar_tramos, _pedir_json_bcrp

# Nota: para series diarias el BCRP devuelve "Set" para setiembre (distinto de "Sep" en mensuales).
MESES_ES = {
    "Ene": 1,
    "Feb": 2,
    "Mar": 3,
    "Abr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Ago": 8,
    "Set": 9,
    "Oct": 10,
    "Nov": 11,
    "Dic": 12,
}

# Cadena de códigos por producto, en orden cronológico.
# El mes compartido entre dos tramos consecutivos (ej. "2023-3" como fin de uno
# e inicio del siguiente) es el MES DE EMPALME: el BCRP publica ambos códigos ese
# mes, y se usa esa razón para reescalar todo el tramo anterior.
MIGRACIONES_BCRP = {
    "REGULAR": [("PN01437PM", None, "2023-3"), ("PN40408PM", "2023-3", None)],
    "PREMIUM": [("PN01438PM", None, "2023-3"), ("PN40409PM", "2023-3", None)],
    "BIODIESEL": [("PN01441PM", None, None)],
    "GLP": [("PN01442PM", None, None)],
}


def extraer_excel(contenido_archivo: bytes) -> pd.DataFrame:
    """Extrae las transacciones de ventas desde el archivo Excel original."""
    df = pd.read_excel(io.BytesIO(contenido_archivo), skiprows=8, header=None)

    filtro_articulos = df[0].astype(str).str.strip() == "ARTICULO:"
    df.loc[filtro_articulos, "producto"] = (
        df.loc[filtro_articulos, 2].astype(str).str.strip()
    )
    df["producto"] = df["producto"].ffill()
    # qué hace ffill?
    # por qué lo quitas?
    df_ventas = df[~filtro_articulos].copy()

    # qué es el subset?
    df_ventas = df_ventas.dropna(subset=[0, 1], how="all")

    columnas_a_mantener = [0, 16, 18, 20, 22, "producto"]
    df_ventas = df_ventas[columnas_a_mantener].copy()

    df_ventas.columns = ["fecha", "cantidad", "precio", "venta", "importe", "producto"]
    df_ventas = df_ventas.iloc[1:].reset_index(drop=True)

    # Estandarizar la fecha para el resto del pipeline
    df_ventas["fecha"] = pd.to_datetime(df_ventas["fecha"], format="%d/%m/%y")
    return df_ventas


def extraer_txt(contenido_archivo: bytes) -> pd.DataFrame:
    """Extrae las transacciones desde un archivo TXT en formato separado por pipes (|)."""
    contenido = contenido_archivo.decode("latin-1")

    if "|" not in contenido.splitlines()[0]:
        raise ValueError(
            "El archivo no viene en formato pipe (|) esperado. "
            "Revisa si este año/archivo usa una estructura distinta antes de continuar."
        )

    df = pd.read_csv(io.StringIO(contenido), sep="|", header=None, engine="python")
    # Formato del contador: 0=Fecha, 1=TipoComprobante, 2=Serie, 3=Numero,
    # 11=ProductoCode, 13=Cantidad, 14=Precio, 15=Venta, 16=Importe
    columnas = [0, 1, 2, 3, 11, 13, 14, 15, 16]
    df = df[columnas].copy()
    df.columns = [
        "fecha",
        "tipo_comprobante",
        "serie",
        "numero",
        "producto",
        "cantidad",
        "precio",
        "venta",
        "importe",
    ]

    # Codigo de boleta/comprobante en formato estandar peruano: Serie-Numero (ej. "F003-49555")
    df["codigo_boleta"] = df["serie"].astype(str) + "-" + df["numero"].astype(str)
    df = df.drop(columns=["serie", "numero"])

    df["fecha"] = df["fecha"].astype(str).str.split(" ").str[0]
    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y")

    df["producto"] = df["producto"].astype(str).str.replace(r"\.0", "", regex=True)

    # Cantidad: se preserva el signo (tipo_comprobante == "NOT" puede traer cantidad
    # negativa -- son correcciones/reversiones, no ventas nuevas).
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
    for c in ["precio", "venta", "importe"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").abs()

    return df


def obtener_data_eia(
    fecha_inicio: str,
    fecha_fin: str,
    api_key: str,
    series_id: str = "RWTC",
    value_name: str = "precio_wti_usd",
) -> pd.DataFrame:
    """
    Obtiene precios internacionales de petróleo (diarios) desde la API de la EIA.

    fecha_inicio, fecha_fin : "YYYY-MM-DD"
    api_key : API key de la EIA
    series_id : "RWTC" = WTI Cushing OK (default) | "RBRTE" = Brent
    value_name : nombre de la columna de valor en el DataFrame resultante
    """
    url = "https://api.eia.gov/v2/petroleum/pri/spt/data/"

    params = {
        "api_key": api_key,
        "frequency": "daily",
        "data[0]": "value",
        "facets[series][]": series_id,
        "start": fecha_inicio,
        "end": fecha_fin,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,  # la API pagina de a 5000 filas máx; subirlo si el rango de fechas es muy largo
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        print(f"Error al conectar con EIA: código {response.status_code}")
        print(response.text[:300])
        return None

    data = response.json()
    registros = data.get("response", {}).get("data", [])

    if not registros:
        print("La API respondió sin datos. Revisa el series_id o el rango de fechas.")
        return None

    df = pd.DataFrame(registros)
    df = df.rename(columns={"period": "fecha", "value": value_name})
    df["fecha"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d")
    df[value_name] = pd.to_numeric(df[value_name], errors="coerce")
    df = df[["fecha", value_name]].sort_values("fecha").reset_index(drop=True)

    return df


def obtener_data_bcrp_cambio_dolar(
    codigo: str, fecha_inicio: str, fecha_fin: str
) -> pd.DataFrame:
    """Descarga una serie diaria del BCRP y la devuelve como DataFrame(fecha, valor)."""
    url = (
        f"https://estadisticas.bcrp.gob.pe/estadisticas/series/api/"
        f"{codigo}/json/{fecha_inicio}/{fecha_fin}/esp"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    data = _pedir_json_bcrp(url, headers)

    filas = []
    for periodo in data.get("periods", []):
        dia_str, mes_str, anio_str = periodo["name"].split(".")
        anio = 2000 + int(anio_str)
        fecha = pd.Timestamp(year=anio, month=MESES_ES[mes_str], day=int(dia_str))
        valor_raw = periodo["values"][0]
        valor = None if valor_raw == "n.d." else float(valor_raw)
        filas.append({"fecha": fecha, "valor": valor})

    return pd.DataFrame(filas)


def obtener_data_meteorologica(
    fecha_inicio: str,
    fecha_fin: str,
    latitud: float = -6.7714,
    longitud: float = -79.8409,
) -> pd.DataFrame:
    """
    Obtiene temperatura máxima, mínima y precipitación diaria desde la API histórica
    de Open-Meteo (gratuita, sin API key).

    fecha_inicio, fecha_fin : "YYYY-MM-DD"
    latitud, longitud : coordenadas del grifo (default: Lima, Perú; ajusta a la ubicación real)
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitud,
        "longitude": longitud,
        "start_date": fecha_inicio,
        "end_date": fecha_fin,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
        "timezone": "America/Lima",
    }

    response = requests.get(url, params=params)

    if response.status_code != 200:
        print(f"Error al conectar con Open-Meteo: código {response.status_code}")
        print(response.text[:300])
        return None

    diario = response.json().get("daily", {})

    df = pd.DataFrame(
        {
            "fecha": pd.to_datetime(diario.get("time", [])),
            "temperatura_max": diario.get("temperature_2m_max", []),
            "temperatura_min": diario.get("temperature_2m_min", []),
            "precipitacion_mm": diario.get("precipitation_sum", []),
        }
    )

    return df


def obtener_data_bcrp_indices(fecha_inicio: str, fecha_fin: str) -> pd.DataFrame:
    """
    Trae el índice de precio de combustible del BCRP para REGULAR, PREMIUM, BIODIESEL
    y GLP en una sola llamada, empalmando automáticamente los códigos que cambiaron
    de denominación (90/95 octanos -> Regular/Premium, marzo 2023).

    fecha_inicio, fecha_fin: "YYYY-M" (formato de la API del BCRP).

    Devuelve un DataFrame largo: ['fecha', 'producto', 'precio_combustible_bcrp'],
    listo para unir con tu df_diario por ['fecha' (o año-mes), 'producto'].
    """
    piezas = []
    for producto, tramos in MIGRACIONES_BCRP.items():
        df_producto = _empalmar_tramos(tramos, fecha_inicio, fecha_fin)
        df_producto = df_producto.rename(columns={"valor": "precio_combustible_bcrp"})
        df_producto["producto"] = producto
        piezas.append(df_producto)

    resultado = pd.concat(piezas, ignore_index=True)
    resultado = resultado[
        (resultado["fecha"] >= _a_timestamp(fecha_inicio))
        & (resultado["fecha"] <= _a_timestamp(fecha_fin))
    ]
    return (
        resultado[["fecha", "producto", "precio_combustible_bcrp"]]
        .sort_values(["producto", "fecha"])
        .reset_index(drop=True)
    )

