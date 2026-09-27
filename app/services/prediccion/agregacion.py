"""Agregación de las transacciones de venta a nivel diario x producto.

Segundo paso de la ingesta: de las transacciones que devuelve
:mod:`app.services.prediccion.extraccion` a la fila diaria por producto que se guarda
en ``historial_ventas``.

Copia fiel de ``limpiar_datos`` en ``jupyter/notebooks/dataframe.ipynb``: es la misma
agregación con la que se construyó el dataset de entrenamiento, y
``tests/test_ingesta_xlsx.py`` lo comprueba contra ``df_diario.parquet``.
"""

import holidays
import pandas as pd

# Código de artículo del contador -> producto normalizado. Mismo mapa que
# ``dataframe.ipynb``: los códigos 33/34 son los de la norma nueva y conviven con los
# antiguos en el histórico, así que ambos deben estar.
MAPA_PRODUCTOS = {
    "2": "BIODIESEL",
    "3": "REGULAR",  # Gasohol 84
    "4": "REGULAR",  # Gasohol 90
    "5": "PREMIUM",  # Gasohol 95
    "8": "GLP",
    "34": "REGULAR",  # Norma nueva
    "33": "PREMIUM",  # Norma nueva
}

# Umbral de "transacción grande" en GALONES, específico por producto. Los volúmenes
# típicos de GLP vehicular y de REGULAR no son comparables, por eso no puede usarse un
# solo número para todos. Alimenta ``proporcion_transacciones_grandes``, de donde sale
# la feature ``prop_grandes_lag_1``.
UMBRAL_GRANDE = {
    "REGULAR": 30,
    "PREMIUM": 25,
    "BIODIESEL": 40,
    "GLP": 10,
}


def construir_calendario(fecha_min, fecha_max) -> pd.DataFrame:
    """Tabla de un renglón por día con las variables de calendario.

    Se calcula sobre fechas ÚNICAS y luego se une, en lugar de aplicarse fila por fila
    sobre las ~33k transacciones mensuales, que repetía el mismo cálculo miles de veces.
    """
    fechas = pd.date_range(fecha_min, fecha_max, freq="D")
    cal = pd.DataFrame({"fecha": fechas})

    cal["dia"] = cal["fecha"].dt.day
    cal["mes"] = cal["fecha"].dt.month
    cal["year"] = cal["fecha"].dt.year
    cal["dia_semana"] = cal["fecha"].dt.dayofweek
    cal["semana"] = cal["fecha"].dt.isocalendar().week.astype(int)
    cal["fin_de_semana"] = cal["dia_semana"] >= 5
    cal["trimestre"] = cal["fecha"].dt.quarter
    cal["dia_del_year"] = cal["fecha"].dt.dayofyear

    # years=range(...) puebla los feriados de golpe. Sin ese argumento, holidays.PE()
    # arranca vacío y se va poblando de forma perezosa según se consulta, lo que hace
    # que inspeccionarlo antes de usarlo devuelva resultados engañosos.
    pe_holidays = holidays.PE(years=range(fecha_min.year, fecha_max.year + 1))
    cal["feriado"] = cal["fecha"].apply(lambda d: int(d in pe_holidays))
    cal["es_vispera_navidad"] = (cal["mes"] == 12) & (cal["dia"] == 24)
    cal["es_vispera_year_nuevo"] = (cal["mes"] == 12) & (cal["dia"] == 31)
    cal["es_vispera_semana_santa"] = cal["fecha"].apply(
        lambda d: pe_holidays.get(d + pd.Timedelta(days=1)) == "Jueves Santo"
    )
    cal["es_vispera_feriado_general"] = cal["fecha"].apply(
        lambda d: ((d + pd.Timedelta(days=1)) in pe_holidays) and (d not in pe_holidays)
    )
    return cal


def limpiar_datos(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra, tipa y agrega las transacciones a nivel diario x producto.

    Produce las cuatro columnas crudas que alimentan la inferencia (``cantidad``,
    ``precio_promedio``, ``n_transacciones_totales``,
    ``proporcion_transacciones_grandes``) más el calendario.

    En días sin ninguna venta, ``cantidad`` y los conteos van a 0 (un hueco en una
    serie de tiempo no es lo mismo que un cero real), pero ``precio_promedio`` y
    ``proporcion_transacciones_grandes`` quedan en NA a propósito: ese día no hubo un
    precio real. El arrastre (ffill) se aplica al guardar, no aquí.
    """
    df = df.copy()

    for c in ["cantidad", "precio", "venta"]:
        df[c] = df[c].astype(str).str.strip().str.replace(",", "", regex=False)
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[df["producto"].isin(MAPA_PRODUCTOS.keys())].copy()
    df["producto"] = df["producto"].map(MAPA_PRODUCTOS)
    df = df.reset_index(drop=True)

    if df.empty:
        raise ValueError(
            "El archivo no contiene ninguna venta de los productos conocidos "
            f"(códigos {', '.join(sorted(MAPA_PRODUCTOS))}). Revisa que sea el "
            "reporte de ventas de combustible y no otro."
        )

    # Marca de transacción grande ANTES de agregar: se evalúa transacción por transacción.
    df["es_transaccion_grande"] = df["cantidad"] > df["producto"].map(UMBRAL_GRANDE)

    df["ingreso_dinero"] = df["cantidad"] * df["precio"]

    df_diario = (
        df.groupby(["fecha", "producto"])
        .agg(
            cantidad=("cantidad", "sum"),
            ingreso_dinero=("ingreso_dinero", "sum"),
            # nunique sobre el comprobante y no size sobre las filas: un mismo
            # comprobante puede traer varias líneas (p. ej. combustible + gaseosa).
            n_transacciones_totales=("codigo_boleta", "nunique"),
            n_transacciones_grandes=("es_transaccion_grande", "sum"),
            cantidad_max_transaccion=("cantidad", "max"),
        )
        .reset_index()
    )

    # --- Huecos -> ceros reales: calendario completo x producto ---
    # groupby solo genera las combinaciones (fecha, producto) que existen. Si un día no
    # hubo ventas de BIODIESEL (desabastecimiento, por ejemplo), esa fila simplemente no
    # aparece. Para una serie de tiempo un hueco silencioso no es lo mismo que un cero
    # real, así que se reindexa el calendario completo.
    fecha_min, fecha_max = df_diario["fecha"].min(), df_diario["fecha"].max()
    productos = df_diario["producto"].unique()
    indice_completo = pd.MultiIndex.from_product(
        [pd.date_range(fecha_min, fecha_max, freq="D"), productos],
        names=["fecha", "producto"],
    )
    df_diario = (
        df_diario.set_index(["fecha", "producto"])
        .reindex(indice_completo)
        .reset_index()
    )

    for c in [
        "cantidad",
        "ingreso_dinero",
        "n_transacciones_totales",
        "n_transacciones_grandes",
    ]:
        df_diario[c] = df_diario[c].fillna(0)

    df_diario["n_transacciones_totales"] = df_diario["n_transacciones_totales"].astype(
        int
    )
    df_diario["n_transacciones_grandes"] = df_diario["n_transacciones_grandes"].astype(
        int
    )
    df_diario["n_transacciones_normales"] = (
        df_diario["n_transacciones_totales"] - df_diario["n_transacciones_grandes"]
    )

    # --- Variables de calendario, calculadas una vez y unidas ---
    calendario = construir_calendario(fecha_min, fecha_max)
    df_diario = df_diario.merge(calendario, on="fecha", how="left")

    # --- Derivadas ---
    # En días con 0 transacciones estas quedan en NA a propósito: no hubo un precio ni un
    # ticket promedio real ese día. NO se rellenan con 0 (distorsionaría la variable de
    # precio); el ffill por producto se aplica al consolidar.
    sin_ventas = df_diario["n_transacciones_totales"] == 0

    df_diario["precio_promedio"] = (
        df_diario["ingreso_dinero"] / df_diario["cantidad"]
    ).round(2)
    df_diario["cantidad_promedio_transaccion"] = (
        df_diario["cantidad"] / df_diario["n_transacciones_totales"]
    ).round(3)
    df_diario["proporcion_transacciones_grandes"] = (
        df_diario["n_transacciones_grandes"] / df_diario["n_transacciones_totales"]
    ).round(4)

    for c in [
        "precio_promedio",
        "cantidad_promedio_transaccion",
        "proporcion_transacciones_grandes",
        "cantidad_max_transaccion",
    ]:
        df_diario.loc[sin_ventas, c] = pd.NA

    df_diario = df_diario.drop(columns=["ingreso_dinero"])

    return df_diario
