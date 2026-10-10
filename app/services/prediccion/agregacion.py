"""
Agregación de las transacciones de venta a nivel diario por producto

Segundo paso de la ingesta

Recibe las transacciones sueltas que devuelve ``extraer_excel`` (una fila por línea
de boleta) y las convierte en una tabla de UNA fila por (día, producto):

1. Limpia los números (quita comas, convierte a float) y traduce los códigos de
   producto del reporte a los 4 productos del modelo (MAPA_PRODUCTOS).
2. Marca cada transacción como "grande" o no, según el umbral de su producto.
3. Agrupa por (fecha, producto) y resume: galones vendidos, dinero, n° de boletas...
4. Rellena los días sin ventas con ceros explícitos (calendario completo).
5. Une las variables de calendario (día de semana, feriados, vísperas...).
6. Calcula las derivadas: precio_promedio, proporcion_transacciones_grandes, etc.

Esto se guarda en ``historial_ventas``.
"""

import holidays
import pandas as pd


MAPA_PRODUCTOS = {
    "2": "BIODIESEL",
    "3": "REGULAR",  # Gasohol 84
    "4": "REGULAR",  # Gasohol 90
    "5": "PREMIUM",  # Gasohol 95
    "8": "GLP",
    "34": "REGULAR",  # Norma nueva
    "33": "PREMIUM",  # Norma nueva
}

# Umbral de "transacción grande" en GALONES, específico por producto.
# Los volúmenes típicos de GLP vehicular y de REGULAR no son comparables,
# por eso no puede usarse un solo número para todos.
# Alimenta: proporcion_transacciones_grandes, de donde sale la feature: prop_grandes_lag_1

UMBRAL_GRANDE = {
    "REGULAR": 30,
    "PREMIUM": 25,
    "BIODIESEL": 40,
    "GLP": 10,
}


def construir_calendario(fecha_min, fecha_max) -> pd.DataFrame:
    """
    Tabla de un renglón por día con las variables de calendario.

    Se calcula sobre fechas ÚNICAS y luego se une, en lugar de aplicarse fila por fila
    sobre las ~33k transacciones mensuales, que repetía el mismo cálculo miles de veces.
    """

    fechas = pd.date_range(fecha_min, fecha_max, freq="D")
    calendario = pd.DataFrame({"fecha": fechas})

    calendario["dia"] = calendario["fecha"].dt.day
    calendario["mes"] = calendario["fecha"].dt.month
    calendario["year"] = calendario["fecha"].dt.year
    calendario["dia_semana"] = calendario["fecha"].dt.dayofweek
    calendario["semana"] = calendario["fecha"].dt.isocalendar().week.astype(int)
    calendario["fin_de_semana"] = calendario["dia_semana"] >= 5
    calendario["trimestre"] = calendario["fecha"].dt.quarter
    calendario["dia_del_year"] = calendario["fecha"].dt.dayofyear


    pe_holidays = holidays.PE(years=range(fecha_min.year, fecha_max.year + 1))
    calendario["feriado"] = calendario["fecha"].apply(lambda d: int(d in pe_holidays))
    calendario["es_vispera_navidad"] = (calendario["mes"] == 12) & (calendario["dia"] == 24)
    calendario["es_vispera_year_nuevo"] = (calendario["mes"] == 12) & (calendario["dia"] == 31)


    
    calendario["es_vispera_semana_santa"] = calendario["fecha"].apply(
        lambda d: pe_holidays.get(d + pd.Timedelta(days=1)) == "Jueves Santo"
    )
    # Toma la fecha actual d.
    # Le suma un día: d + pd.Timedelta(days=1) (mira el día siguiente).
    # Consulta en pe_holidays.get(...) si el día siguiente está registrado como feriado y si su nombre exacto es "Jueves Santo".
    # Retorna True si mañana es Jueves Santo
    #   es decir, hoy es Miércoles Santo, y False para el resto de días.

    calendario["es_vispera_feriado_general"] = calendario["fecha"].apply(
        lambda d: ((d + pd.Timedelta(days=1)) in pe_holidays) and (d not in pe_holidays)
    )
    # Evalúa dos condiciones juntas:
    # (d + pd.Timedelta(days=1)) in pe_holidays: El día siguiente sí es feriado.
    # d not in pe_holidays: El día de hoy no es feriado.

    return calendario



def limpiar_datos(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra, tipa y agrega las transacciones a nivel diario por producto.

    Produce las cuatro columnas crudas que alimentan la inferencia 
        cantidad,
        precio_promedio,
        n_transacciones_totales,
        proporcion_transacciones_grandes
    más el calendario.

    En días sin ninguna venta, ``cantidad`` y los conteos van a 0
        un hueco en una serie de tiempo no es lo mismo que un cero real,
    pero ``precio_promedio`` y ``proporcion_transacciones_grandes`` quedan en NA a propósito
        ese día no hubo un precio real
    
    El arrastre (ffill) se aplica al guardar, no aquí.
    """
    df = df.copy()

    for c in ["cantidad", "precio", "venta"]:
        df[c] = df[c].astype(str).str.strip().str.replace(",", "", regex=False)
        df[c] = pd.to_numeric(df[c], errors="coerce") #la transforma en NaN si no encuentra valor

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

    # --- Agregación diaria ---
    # groupby(["fecha", "producto"]) junta en un mismo "grupo" todas las filas que comparten fecha Y producto.
    #   Ej.: todas las transacciones de REGULAR del 03/05.
    #
    # .agg(...) resume cada grupo en UNA sola fila. La sintaxis es:
    #     nombre_columna_nueva=("columna_origen", "función")
    # es decir, "aplica esta función a esta columna dentro de cada grupo".
    #
    # Ejemplo con 3 transacciones de REGULAR el 03/05:
    #     cantidad = 10, 35, 5   es_transaccion_grande = F, T, F
    #  -> cantidad=50 (sum), n_transacciones_grandes=1 (sum de True cuenta 1),
    #     cantidad_max_transaccion=35 (max)
    #
    # Tras el groupby, fecha y producto quedan como índice (no como columnas);
    # .reset_index() las devuelve a columnas normales.
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
    # groupby solo genera las combinaciones (fecha, producto) que existen.
    #   Si en un día no hubo ventas de BIODIESEL (desabastecimiento, por ejemplo),
    #   esa fila simplemente no aparece.
    # Para una serie de tiempo un hueco silencioso no es lo mismo que un cero
    # real, así que se reindexa el calendario completo.

    fecha_min, fecha_max = df_diario["fecha"].min(), df_diario["fecha"].max()

    productos = df_diario["producto"].unique()

    # Un MultiIndex es un índice de filas con MÁS de un nivel: cada fila se
    # identifica por una pareja (fecha, producto) en vez de por un solo valor.
    #
    # from_product arma el producto cartesiano: TODAS las fechas del rango
    # combinadas con TODOS los productos. Con 3 días y 2 productos:
    #     (01/05, REGULAR) (01/05, GLP)
    #     (02/05, REGULAR) (02/05, GLP)
    #     (03/05, REGULAR) (03/05, GLP)
    # Es la "plantilla" de filas que DEBERÍAN existir.
    indice_completo = pd.MultiIndex.from_product(
        [pd.date_range(fecha_min, fecha_max, freq="D"), productos],
        names=["fecha", "producto"],
    )

    # 1. set_index: convierte fecha y producto en índice, para que df_diario tenga
    #    el mismo tipo de índice (fecha, producto) que la plantilla.
    # 2. reindex: reordena df_diario según la plantilla. Las parejas que ya
    #    existían conservan sus valores; las que faltaban (ej. (02/05, GLP) si ese
    #    día no se vendió GLP) se CREAN con todas sus columnas en NaN.
    # 3. reset_index: devuelve fecha y producto a columnas normales, para poder
    #    hacer después el merge con el calendario por "fecha".
    #
    # Los NaN de las filas nuevas se convierten en 0 justo abajo (fillna).
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
