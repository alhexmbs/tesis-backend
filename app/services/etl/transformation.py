import holidays
import pandas as pd

MAPA_PRODUCTOS = {
    "2-BIODIESEL B5 UV": "BIODIESEL",
    "8-GLP": "GLP",
    "12-GASOHOL REGULAR": "REGULAR",
    "13-GASOHOL PREMIUM": "PREMIUM",
    "3-GASOHOL 84": "REGULAR",
    "4-GASOHOL 90": "REGULAR",
    "5-GASOHOL 95": "PREMIUM",
    # Mapeos para el formato separado por pipes (2024 en adelante) donde solo viene el ID
    "2": "BIODIESEL",
    "8": "GLP",
    "12": "REGULAR",
    "13": "PREMIUM",
    "3": "REGULAR",  # Gasohol 84 -> Regular (mismo criterio que con Royal Prix)
    "4": "REGULAR",  # Gasohol 90 -> Regular
    "5": "PREMIUM",  # Gasohol 95 -> Premium
}


def limpiar_datos(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra, tipa y agrupa los datos de manera diaria con sus variables estáticas."""
    # Convertir montos string a float
    for c in ["cantidad", "precio", "venta", "importe"]:
        df[c] = df[c].astype(str).str.strip().str.replace(",", "", regex=False)
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[df["producto"].isin(MAPA_PRODUCTOS.keys())].copy()
    df["producto"] = df["producto"].map(MAPA_PRODUCTOS)
    df = df.reset_index(drop=True)

    df["dia"] = df["fecha"].dt.day
    df["mes"] = df["fecha"].dt.month
    df["year"] = df["fecha"].dt.year
    df["dia_semana"] = df["fecha"].dt.dayofweek
    df["semana"] = df["fecha"].dt.isocalendar().week
    df["fin_de_semana"] = df["dia_semana"] >= 5
    df["trimestre"] = df["fecha"].dt.quarter
    df["dia_del_year"] = df["fecha"].dt.dayofyear

    pe_holidays = holidays.PE()
    df["feriado"] = df["fecha"].apply(lambda d: int(d in pe_holidays))
    df["es_vispera_navidad"] = (df["fecha"].dt.month == 12) & (df["fecha"].dt.day == 24)
    df["es_vispera_year_nuevo"] = (df["fecha"].dt.month == 12) & (
        df["fecha"].dt.day == 31
    )
    df["es_vispera_semana_santa"] = df["fecha"].apply(
        lambda d: pe_holidays.get(d + pd.Timedelta(days=1)) == "Jueves Santo"
    )
    df["es_vispera_feriado_general"] = df["fecha"].apply(
        lambda d: ((d + pd.Timedelta(days=1)) in pe_holidays) and (d not in pe_holidays)
    )

    df["ingreso_dinero"] = df["cantidad"] * df["precio"]

    df_diario = (
        df.groupby(["fecha", "producto"])
        .agg(
            {
                "cantidad": "sum",
                "ingreso_dinero": "sum",
                "feriado": "max",
                "fin_de_semana": "max",
                "es_vispera_navidad": "max",
                "es_vispera_year_nuevo": "max",
                "es_vispera_semana_santa": "max",
                "es_vispera_feriado_general": "max",
                "year": "first",
                "mes": "first",
                "dia": "first",
                "dia_semana": "first",
                "semana": "first",
                "trimestre": "first",
                "dia_del_year": "first",
            }
        )
        .reset_index()
    )

    df_diario["precio_promedio"] = (
        df_diario["ingreso_dinero"] / df_diario["cantidad"]
    ).round(2)
    df_diario = df_diario.drop(columns=["ingreso_dinero"])

    return df_diario


def feature_engineering(
    df_diario: pd.DataFrame, historico_dicts: list = None
) -> pd.DataFrame:
    """Une el contexto histórico y calcula rezagos (lags) y medias móviles."""
    if historico_dicts:
        df_historico = pd.DataFrame(historico_dicts)
        if not df_historico.empty:
            df_historico["fecha"] = pd.to_datetime(df_historico["fecha"])
            fecha_minima_nueva = df_diario["fecha"].min()
            df_historico = df_historico[df_historico["fecha"] < fecha_minima_nueva]
            df_diario = pd.concat([df_historico, df_diario], ignore_index=True)

    df_diario = df_diario.sort_values(by=["producto", "fecha"]).reset_index(drop=True)

    df_diario["ventas_hace_1_dia"] = df_diario.groupby("producto")["cantidad"].shift(1)
    df_diario["ventas_hace_2_dias"] = df_diario.groupby("producto")["cantidad"].shift(2)
    df_diario["ventas_hace_7_dias"] = df_diario.groupby("producto")["cantidad"].shift(7)

    df_diario["promedio_ultimos_3_dias"] = df_diario.groupby("producto")[
        "cantidad"
    ].transform(lambda x: x.shift(1).rolling(window=3).mean())
    df_diario["promedio_ultimos_7_dias"] = df_diario.groupby("producto")[
        "cantidad"
    ].transform(lambda x: x.shift(1).rolling(window=7).mean())

    df_diario["promedio_ultimos_3_dias"] = df_diario["promedio_ultimos_3_dias"].round(2)
    df_diario["promedio_ultimos_7_dias"] = df_diario["promedio_ultimos_7_dias"].round(2)

    return df_diario
