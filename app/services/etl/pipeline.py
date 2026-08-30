import pandas as pd
from sqlalchemy.orm import Session

from app.services.etl.carga import guardar_ventas_historicas, obtener_historico_para_lags
from app.services.etl.extraction import extraer_excel, extraer_txt
from app.services.etl.transformation import feature_engineering, limpiar_datos

COLUMNAS_MACRO = (
    "precio_wti_usd",
    "precio_combustible_bcrp",
    "tipo_cambio_venta",
    "temperatura_max",
    "temperatura_min",
    "precipitacion_mm",
)


def procesar_solo_ventas(
    contenido: bytes, filename: str | None, db: Session
) -> dict:
    """Guarda solo las ventas propias del archivo subido en ventas_historicas (cantidad,
    precio, calendario, lags), sin llamar a las 4 fuentes externas (WTI, BCRP tipo de
    cambio, BCRP índices, clima). Las columnas macro quedan en NULL para esas filas."""
    if filename and filename.lower().endswith((".xlsx", ".xls")):
        df_ventas_crudo = extraer_excel(contenido)
    else:
        df_ventas_crudo = extraer_txt(contenido)

    df_diario = limpiar_datos(df_ventas_crudo)

    fecha_min = df_diario["fecha"].min()
    fecha_max = df_diario["fecha"].max()

    productos = df_diario["producto"].unique().tolist()
    historico_dicts = obtener_historico_para_lags(db, fecha_min.date(), productos)

    df_features = feature_engineering(df_diario, historico_dicts)

    # feature_engineering antepone historial previo (para poder calcular los lags de
    # los primeros días del lote); se recorta de vuelta al rango del archivo subido.
    df_features = df_features[
        (df_features["fecha"] >= fecha_min) & (df_features["fecha"] <= fecha_max)
    ]

    for columna in COLUMNAS_MACRO:
        df_features[columna] = None

    guardar_ventas_historicas(db, df_features)

    return {
        "filas_procesadas": len(df_features),
        "fecha_inicio": fecha_min.strftime("%Y-%m-%d"),
        "fecha_fin": fecha_max.strftime("%Y-%m-%d"),
    }


def construir_dataset_modelo(
    df_ventas, df_wti, df_precios_combustible, df_tipo_cambio, df_clima
) -> pd.DataFrame:
    """Une todas las fuentes en una sola tabla, a nivel fecha x producto, lista para el modelo."""
    df = df_ventas.copy()

    df = df.merge(df_wti, on="fecha", how="left")
    df["precio_wti_usd"] = df["precio_wti_usd"].ffill()

    df = df.merge(df_clima, on="fecha", how="left")

    df["anio_mes"] = df["fecha"].values.astype("datetime64[M]")

    precios = df_precios_combustible.copy()
    precios["anio_mes"] = precios["fecha"].values.astype("datetime64[M]")
    df = df.merge(
        precios[["anio_mes", "producto", "precio_combustible_bcrp"]],
        on=["anio_mes", "producto"],
        how="left",
    )

    df = df.merge(
        df_tipo_cambio[["fecha", "tipo_cambio_venta"]], on="fecha", how="left"
    )
    df["tipo_cambio_venta"] = df["tipo_cambio_venta"].ffill()

    return df.drop(columns=["anio_mes"])
