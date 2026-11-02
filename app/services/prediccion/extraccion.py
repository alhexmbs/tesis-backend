"""
Lectura del reporte mensual de ventas (.xlsx) que exporta el sistema del grifo.

Primer paso de la ingesta:
    convierte el archivo de ventas .xslx en un DataFrame de transacciones
"""

import io

import pandas as pd

# Columnas del reporte que la ingesta necesita. Si falta alguna, el archivo no es el
# reporte esperado y se avisa, en vez de fallar más abajo con un KeyError que no le
# dice nada al usuario.
COLUMNAS_REQUERIDAS_XLSX = (
    "Tipo_Comprob",
    "Serie",
    "Correlativo",
    "Fecha_Comprob",
    "Cod_Art",
    "Cantidad",
    "Valor_Venta",
)


def extraer_excel(contenido_archivo: bytes) -> pd.DataFrame:
    """
    Extrae las transacciones de venta del reporte mensual .xlsx del contador.

    El esquema de salida
    ->    (fecha, codigo_boleta, tipo_comprobante, producto, cantidad, precio, venta)
    
    es el que espera la función de
    ->    app.services.prediccion.agregacion.limpiar_datos
    
    codigo_boleta en particular es imprescindible para contar transacciones sin
    inflar el conteo cuando un mismo comprobante trae varias líneas.

    ---------------------------------------------------------------------------------------------
    |Un archivo de Excel moderno (.xlsx) no es texto plano, sino un archivo binario comprimido  |
    |    básicamente un archivo .zip con XMLs adentro.                                          |
    |                                                                                           |
    |Si se intenta leer como texto (str), fallaría o se corrompería de inmediato                |
    |porque contiene caracteres binarios no decodificables en UTF-8 estándar.                   |
    ---------------------------------------------------------------------------------------------
    """
    df = pd.read_excel(io.BytesIO(contenido_archivo))
    """
    io.BytesIO -> Crea un "archivo virtual" en memoria RAM.
        Envuelve los bytes y los hace comportarse exactamente como si hubiera hecho: df = pd.read_excel(archivo.xlsx)
    """

    faltantes = [c for c in COLUMNAS_REQUERIDAS_XLSX if c not in df.columns]
    if faltantes:
        raise ValueError(
            "El archivo .xlsx no tiene el formato del reporte de ventas esperado. Para más información consulte el manual de usuario en la sección Flujo de carga de reporte de ventas"
        )


    # Código de comprobante: Serie-Correlativo (ej. "F003-49555").
    # El .fillna("nan") NO es cosmético: unas pocas filas del histórico (3 en julio de 2022) vienen sin Serie.
    # Con el dtype string de pandas 3 el NA se propaga y deja
    # codigo_boleta nulo, y como n_transacciones_totales se calcula con nunique, que
    # ignora los nulos, esas transacciones desaparecían del conteo.
    # El notebook, con dtype object, las rendereaba como el texto "nan" y sí las contaba;
    # se reproduce ese mismo comportamiento para no divergir del dato con el que se entrenó

    df["codigo_boleta"] = (
        df["Serie"].astype("object").fillna("nan").astype(str)
        + "-"
        + df["Correlativo"].astype("object").fillna("nan").astype(str)
    )

    df = df.rename(
        columns={
            "Fecha_Comprob": "fecha",
            "Tipo_Comprob": "tipo_comprobante",
            "Cod_Art": "producto",
        }
    )

    df["fecha"] = pd.to_datetime(df["fecha"], format="%d/%m/%Y")

    # producto como string, sin decimales, para poder usar el MISMO MAPA_PRODUCTOS
    # (con claves string) sin importar cómo lo tipó pandas al leer el archivo.
    df["producto"] = df["producto"].astype(str).str.replace(r"\.0", "", regex=True)

    df["cantidad"] = pd.to_numeric(df["Cantidad"], errors="coerce")
    df["venta"] = pd.to_numeric(df["Valor_Venta"], errors="coerce").abs()

    # El xlsx no trae precio unitario directo -> se calcula.
    # Se protege la división:
    # cantidad == 0 daría inf en vez de fallar visiblemente.
    df["precio"] = (df["venta"] / df["cantidad"].replace(0, pd.NA)).abs()

    # Notas de crédito/débito: la cantidad debe ir en negativo para que la suma diaria
    # refleje la devolución. La columna se llama "Tipo_NCND" en los archivos nuevos y
    # "Tipo_NC/ND" (con barra) en los de 2022-2023.

    # Detecta dinámicamente cómo se llama la columna de Notas de Crédito en el Excel y, si existe,
    # convierte en cantidades negativas todos los registros que corresponden a una Nota de Crédito
    # para que resten a la contabilidad.

    col_ncnd = next((c for c in ["Tipo_NCND", "Tipo_NC/ND"] if c in df.columns), None)
    if col_ncnd is not None:
        es_nc = df[col_ncnd].notna()
        df.loc[es_nc, "cantidad"] = -df.loc[es_nc, "cantidad"].abs()

    return df[
        [
            "fecha",
            "codigo_boleta",
            "tipo_comprobante",
            "producto",
            "cantidad",
            "precio",
            "venta",
        ]
    ]
