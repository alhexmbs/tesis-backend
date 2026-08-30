import pandas as pd


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
