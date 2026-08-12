import io

import numpy as np
import pandas as pd


def procesar_excel_ventas(
    contenido_archivo: bytes, historico_dicts: list | None = None
):

    # lectura del archivo directamente desde la memoria RAM (BytesIO)
    df = pd.read_excel(io.BytesIO(contenido_archivo), skiprows=8, header=None)

    # ====================================================================
    # CÓDIGO JUPYTER
    filtro_articulos = df[0].astype(str).str.strip() == "ARTICULO:"
    df.loc[filtro_articulos, "producto"] = (
        df.loc[filtro_articulos, 2].astype(str).str.strip()
    )
    df["producto"] = df["producto"].ffill()
    df_ventas = df[~filtro_articulos].copy()

    MAPA_PRODUCTOS = {
        # NOMBRES HISTÓRICOS (2017 - 2022)
        "3-GASOHOL 84": "REGULAR",  # La demanda de 84 migró a Regular
        "4-GASOHOL 90": "REGULAR",  # 90 es la base natural del Regular
        "5-GASOHOL 95": "PREMIUM",  # 95 es la base natural del Premium
        # NOMBRES ACTUALES -> 2023 en adelante
        "12-GASOHOL REGULAR": "REGULAR",
        "13-GASOHOL PREMIUM": "PREMIUM",
        # OTROS PRODUCTOS que se mantienen en el tiempo
        "2-BIODIESEL B5 UV": "BIODIESEL",
        "8-GLP": "GLP",
    }

    df_ventas = df_ventas[df_ventas["producto"].isin(MAPA_PRODUCTOS.keys())].copy()  # type: ignore
    df_ventas["producto"] = df_ventas["producto"].map(MAPA_PRODUCTOS)  # type: ignore
    df_ventas = df_ventas.reset_index(drop=True)  # type: ignore
    df_ventas = df_ventas.dropna(subset=[0, 1], how="all")  # type: ignore

    columnas_a_mantener = [0, 16, 18, 20, 22, "producto"]
    df_ventas = df_ventas[columnas_a_mantener].copy()
    df_ventas = df_ventas.reset_index(drop=True)

    df_ventas.columns = ["fecha", "cantidad", "precio", "venta", "importe", "producto"]

    df_ventas = df_ventas.iloc[1:].reset_index(drop=True)

    df_ventas["fecha"] = pd.to_datetime(df_ventas["fecha"], format="%d/%m/%y")

    for c in ["cantidad", "precio", "venta", "importe"]:
        df_ventas[c] = (
            df_ventas[c].astype(str).str.strip().str.replace(",", "", regex=False)
        )

        df_ventas[c] = pd.to_numeric(df_ventas[c], errors="coerce")

    df_ventas["dia"] = df_ventas["fecha"].dt.day
    df_ventas["mes"] = df_ventas["fecha"].dt.month
    df_ventas["year"] = df_ventas["fecha"].dt.year
    df_ventas["dia_semana"] = df_ventas["fecha"].dt.dayofweek  # del 0 al 6
    df_ventas["semana"] = df_ventas["fecha"].dt.isocalendar().week
    df_ventas["fin_de_semana"] = df_ventas["dia_semana"] >= 5

    import holidays

    pe_holidays = holidays.PE()

    df_merged = df_ventas.copy()

    # 1. ¿Es feriado?
    df_merged["feriado"] = df_merged["fecha"].apply(lambda d: int(d in pe_holidays))

    # 2. Vísperas fijas
    df_merged["es_vispera_navidad"] = (df_merged["fecha"].dt.month == 12) & (
        df_merged["fecha"].dt.day == 24
    )
    df_merged["es_vispera_year_nuevo"] = (df_merged["fecha"].dt.month == 12) & (
        df_merged["fecha"].dt.day == 31
    )

    # 3. Víspera de Semana Santa (Miércoles Santo, día anterior a Jueves Santo)
    df_merged["es_vispera_semana_santa"] = df_merged["fecha"].apply(
        lambda d: pe_holidays.get(d + pd.Timedelta(days=1)) == "Jueves Santo"
    )

    # 4. Víspera de feriado general (mañana es feriado, pero hoy NO lo es)
    df_merged["es_vispera_feriado_general"] = df_merged["fecha"].apply(
        lambda d: ((d + pd.Timedelta(days=1)) in pe_holidays) and (d not in pe_holidays)
    )

    df_merged = df_merged.drop(columns=["venta", "importe"])

    df_merged["trimestre"] = df_merged["fecha"].dt.quarter
    df_merged["dia_del_year"] = df_merged["fecha"].dt.dayofyear

    # ANTES de agrupar: calculamos el ingreso de dinero por cada transacción
    df_merged["ingreso_dinero"] = df_merged["cantidad"] * df_merged["precio"]

    # Agrupamos incluyendo TODAS las columnas a conservar en el .agg()
    df_diario = (
        df_merged.groupby(["fecha", "producto"])
        .agg(
            {
                "cantidad": "sum",  # Sumamos los galones totales del día
                "ingreso_dinero": "sum",  # Sumamos el dinero total del día
                "feriado": "max",  # Conservamos las variables binarias/temporales
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

    # DESPUÉS de agrupar: calculamos el precio promedio ponderado
    df_diario["precio_promedio"] = df_diario["ingreso_dinero"] / df_diario["cantidad"]

    # SOLUCIÓN AL REDONDEO: Redondeamos el precio a 2 decimales
    df_diario["precio_promedio"] = df_diario["precio_promedio"].round(2)

    # Eliminación de la columna auxiliar de dinero
    df_diario = df_diario.drop(columns=["ingreso_dinero"])

    fecha_minima_nueva = df_diario["fecha"].min()

    if historico_dicts:
        df_historico = pd.DataFrame(historico_dicts)
        if not df_historico.empty:
            df_historico["fecha"] = pd.to_datetime(df_historico["fecha"])
            df_historico = df_historico[df_historico["fecha"] < fecha_minima_nueva]
            df_diario = pd.concat([df_historico, df_diario], ignore_index=True)

    # Ordenamos la tabla cronológicamente para cada producto
    df_diario = df_diario.sort_values(by=["producto", "fecha"]).reset_index(drop=True)  # type: ignore

    # SOLUCIÓN: Para evitar que pandas trate un salto de 3 años como si fuera 1 día,
    # rellenamos los días faltantes usando resample('D') antes de hacer shift() y rolling().
    df_diario = df_diario.set_index("fecha")
    df_diario = (
        df_diario.groupby("producto")
        .resample("D")
        .asfreq()
        .drop(columns=["producto"], errors="ignore")
        .reset_index()
    )

    # ¿Cuánto se vendió hace exactamente 1 día? (Ayer)
    df_diario["ventas_hace_1_dia"] = df_diario.groupby("producto")["cantidad"].shift(1)

    # ¿Cuánto se vendió hace exactamente 2 días?
    df_diario["ventas_hace_2_dias"] = df_diario.groupby("producto")["cantidad"].shift(2)

    # ¿Cuánto se vendió hace exactamente 7 días? (El mismo día de la semana pasada)
    df_diario["ventas_hace_7_dias"] = df_diario.groupby("producto")["cantidad"].shift(7)

    # Promedio de ventas de los últimos 3 días (sin contar hoy)
    df_diario["promedio_ultimos_3_dias"] = df_diario.groupby("producto")["cantidad"].transform(
        lambda x: x.shift(1).rolling(window=3).mean()
    )

    # Promedio de ventas de los últimos 7 días (tendencia semanal)
    df_diario["promedio_ultimos_7_dias"] = df_diario.groupby("producto")["cantidad"].transform(
        lambda x: x.shift(1).rolling(window=7).mean()
    )

    # Eliminamos las filas "vacías" creadas por el resample
    df_diario = df_diario.dropna(subset=["precio_promedio"]).reset_index(drop=True)

    # Cortamos la "cola" histórica que usamos como soporte
    df_diario = df_diario[df_diario["fecha"] >= fecha_minima_nueva].copy()

    # Eliminamos las filas que quedaron con nulos debido a los lags
    df_diario = df_diario.dropna().reset_index(drop=True)

    # Opcional: Redondear los promedios móviles para que la tabla se vea limpia
    df_diario["promedio_ultimos_3_dias"] = df_diario["promedio_ultimos_3_dias"].round(2)
    df_diario["promedio_ultimos_7_dias"] = df_diario["promedio_ultimos_7_dias"].round(2)

    df_final = df_diario
    # --------------------------------------------------

    # Limpieza final crucial para la Base de Datos:
    # Pandas a veces usa "NaN" para vacíos, pero Postgres necesita que sean "None"
    df_final = df_final.replace({np.nan: None})

    # Convertimos el DataFrame a una lista de diccionarios (JSON) para FastAPI
    registros = df_final.to_dict(orient="records")  # type: ignore
    return registros
