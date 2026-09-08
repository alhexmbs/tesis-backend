"""Construcción de las 17 features del modelo de demanda diaria.

FUENTE DE VERDAD: los notebooks ``feature_engineering.ipynb`` (razones frente a
``base_28``, internas, precio) y ``dataframe.ipynb`` (``construir_calendario``).
La lógica se copió de ahí, no se reimplementó de memoria. El test
``tests/test_equivalencia_features.py`` comprueba, a 1e-6, que estas features
coinciden con las que el notebook exportó en ``df_features.parquet``; ese test es
el que garantiza que la extracción fue fiel (el riesgo real es un ``shift`` o un
``rolling`` mal copiado).

Idea central: las features de historia son RAZONES contra ``base_28`` (la media
de la ``cantidad`` de los 28 días anteriores), no niveles en galones. La
predicción del modelo es esa razón y se reconstruye como
``modelo.predict(features) * base_28`` (ver ``servicio.py``). Por eso, para
predecir un día hacen falta al menos los 28 días anteriores de ventas reales; si
no los hay, se levanta ``HistorialInsuficiente`` (que el router traduce a 422).
"""

from __future__ import annotations

import holidays
import numpy as np
import pandas as pd

# Parámetros idénticos a los del notebook y a config_servicio.json.
VENTANA_BASE = 28  # línea base: media de los 28 días ANTERIORES
LAGS_TARGET = (1, 7, 14)  # inercia inmediata, ciclo semanal, confirmación del ciclo
VENTANA_CORTA = 7  # nivel y volatilidad de la última semana

# Columnas crudas diarias (por producto) que alimentan la inferencia. Es
# exactamente el esquema de historial_semilla.csv y de la tabla historial_ventas.
COLUMNAS_HISTORIAL = (
    "cantidad",
    "precio_promedio",
    "n_transacciones_totales",
    "proporcion_transacciones_grandes",
)

# Orden EXACTO en que el modelo espera las 17 features (== config_servicio.json).
# Se define aquí como referencia, pero el orden que se pasa al modelo se toma
# siempre de config_servicio.json en tiempo de predicción.
FEATURES = (
    "mes",
    "dia_semana",
    "feriado",
    "es_vispera_navidad",
    "es_vispera_year_nuevo",
    "es_vispera_semana_santa",
    "es_vispera_feriado_general",
    "temperatura_max",
    "cantidad_lag_1_rel",
    "cantidad_lag_7_rel",
    "cantidad_lag_14_rel",
    "cantidad_roll_mean_7_rel",
    "cantidad_cv_7",
    "n_transacciones_lag_1_rel",
    "prop_grandes_lag_1",
    "precio_promedio_pct_7",
    "regimen_precio",
)


class HistorialInsuficiente(ValueError):
    """No hay suficientes días de historia para construir base_28 o alguna feature.

    El router la traduce a HTTP 422: nunca se devuelve una predicción
    silenciosamente incorrecta por falta de historia.
    """


def _calendario(fecha: pd.Timestamp, pe_holidays: holidays.HolidayBase) -> dict:
    """Variables de calendario para un día, copiadas de ``construir_calendario``.

    ``pe_holidays`` debe construirse con ``holidays.PE(years=range(...))``: sin el
    argumento ``years`` el objeto arranca vacío y se puebla de forma perezosa, con
    lo que ``es_vispera_semana_santa`` quedaría siempre en False sin lanzar error.
    """
    dia_siguiente = fecha + pd.Timedelta(days=1)
    return {
        "mes": int(fecha.month),
        "dia_semana": int(fecha.dayofweek),  # lunes = 0
        "feriado": int(fecha in pe_holidays),
        "es_vispera_navidad": int(fecha.month == 12 and fecha.day == 24),
        "es_vispera_year_nuevo": int(fecha.month == 12 and fecha.day == 31),
        "es_vispera_semana_santa": int(
            pe_holidays.get(dia_siguiente) == "Jueves Santo"
        ),
        "es_vispera_feriado_general": int(
            dia_siguiente in pe_holidays and fecha not in pe_holidays
        ),
    }


def calcular_features_dia(
    historial_previo: pd.DataFrame,
    fecha,
    temperatura_max: float,
    regimen_precio: int,
    precio_previsto: float | None = None,
) -> tuple[dict, float]:
    """Construye las 17 features y ``base_28`` para ``fecha``, de UN solo producto.

    Parameters
    ----------
    historial_previo:
        Filas diarias con columnas ``fecha`` + :data:`COLUMNAS_HISTORIAL`. Solo se
        usan las estrictamente anteriores a ``fecha``. La serie se reindexa a un
        calendario diario completo (igual que el notebook): los días sin ventas se
        rellenan con ``cantidad``/``n_transacciones_totales`` = 0, y
        ``precio_promedio``/``proporcion_transacciones_grandes`` se arrastran con
        ffill.
    fecha:
        Día a predecir.
    temperatura_max:
        Temperatura máxima del día (pronóstico en operación; valor observado en el
        test de equivalencia). Feature contemporánea.
    regimen_precio:
        Régimen de precios congelado del producto (de config_servicio.json).
    precio_previsto:
        ``precio_promedio`` asumido para ``fecha`` (feature contemporánea vía
        ``precio_promedio_pct_7``). Si es ``None`` se arrastra el último precio
        conocido (ffill).

    Returns
    -------
    (features, base_28):
        ``features`` es un dict {nombre: valor} con las 17 features;
        ``base_28`` es el factor de reconstrucción a galones.

    Raises
    ------
    HistorialInsuficiente:
        Si no hay 28 días previos suficientes para ``base_28`` o queda algún NaN.
    """
    fecha = pd.Timestamp(fecha).normalize()

    df = historial_previo.copy()
    if "fecha" not in df.columns:
        raise ValueError("historial_previo debe tener una columna 'fecha'.")
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.normalize()
    df = df[df["fecha"] < fecha].sort_values("fecha")
    # Defensivo: una fecha repetida rompería el reindex al calendario diario.
    df = df.drop_duplicates(subset="fecha", keep="last")

    if df.empty:
        raise HistorialInsuficiente(
            f"No hay historial anterior a {fecha.date()} para construir las features."
        )

    # Fila sintética del día objetivo: solo su precio_promedio entra en las features
    # (vía precio_promedio_pct_7). cantidad/n_transacciones/proporción del propio día
    # nunca se usan (todas las demás features son rezagadas), así que van en NaN.
    fila_objetivo = {
        "fecha": fecha,
        "cantidad": np.nan,
        "precio_promedio": precio_previsto,  # None -> se arrastra con ffill abajo
        "n_transacciones_totales": np.nan,
        "proporcion_transacciones_grandes": np.nan,
    }
    df = pd.concat([df, pd.DataFrame([fila_objetivo])], ignore_index=True)

    # Calendario diario completo [min .. objetivo]: un hueco silencioso no es lo
    # mismo que un cero real en una serie de tiempo, igual que en el notebook.
    calendario_completo = pd.date_range(df["fecha"].min(), fecha, freq="D")
    s = df.set_index("fecha").reindex(calendario_completo)

    # Días sin ventas -> ceros reales en cantidad y nº de transacciones;
    # precio y proporción se arrastran (COLS_FFILL del notebook). El ffill de
    # precio_promedio también resuelve precio_previsto=None (arrastre del último).
    s["cantidad"] = np.maximum(s["cantidad"].fillna(0.0), 0.0)  # truncar en 0 por seguridad
    s["n_transacciones_totales"] = s["n_transacciones_totales"].fillna(0.0)
    s["precio_promedio"] = s["precio_promedio"].ffill()
    s["proporcion_transacciones_grandes"] = s["proporcion_transacciones_grandes"].ffill()

    cantidad = s["cantidad"]

    # --- base_28 y razones (agregar_base_y_razones) ---
    base = cantidad.shift(1).rolling(VENTANA_BASE).mean().replace(0, np.nan)

    razones = {}
    for k in LAGS_TARGET:
        razones[f"cantidad_lag_{k}_rel"] = cantidad.shift(k) / base

    media_corta = cantidad.shift(1).rolling(VENTANA_CORTA).mean()
    desv_corta = cantidad.shift(1).rolling(VENTANA_CORTA).std()
    razones[f"cantidad_roll_mean_{VENTANA_CORTA}_rel"] = media_corta / base
    razones[f"cantidad_cv_{VENTANA_CORTA}"] = desv_corta / media_corta

    # Internas: nunca contemporáneas; n_transacciones frente a su propia media móvil.
    base_trans = (
        s["n_transacciones_totales"].shift(1).rolling(VENTANA_BASE).mean().replace(0, np.nan)
    )
    razones["n_transacciones_lag_1_rel"] = s["n_transacciones_totales"].shift(1) / base_trans
    razones["prop_grandes_lag_1"] = s["proporcion_transacciones_grandes"].shift(1)

    # Precio propio: variación semanal (contemporánea, usa el precio del día objetivo).
    razones["precio_promedio_pct_7"] = s["precio_promedio"].pct_change(7)

    base_28 = base.loc[fecha]
    if pd.isna(base_28):
        raise HistorialInsuficiente(
            f"Historial insuficiente para {fecha.date()}: se necesitan al menos "
            f"{VENTANA_BASE} días anteriores de ventas para calcular la predicción."
        )

    # --- Ensamblado de las 17 features en el orden canónico ---
    pe_holidays = holidays.PE(
        years=range(int(s.index.min().year), int(fecha.year) + 1)
    )
    features = _calendario(fecha, pe_holidays)
    features["temperatura_max"] = float(temperatura_max)
    for nombre, serie in razones.items():
        features[nombre] = float(serie.loc[fecha])
    features["regimen_precio"] = int(regimen_precio)

    faltantes = [n for n in FEATURES if n not in features]
    if faltantes:  # defensivo: nunca debería ocurrir
        raise RuntimeError(f"Features no construidas: {faltantes}")

    nan_features = [n for n in FEATURES if not np.isfinite(features[n])]
    if nan_features:
        raise HistorialInsuficiente(
            f"Historial insuficiente para {fecha.date()}: quedaron features sin valor "
            f"({', '.join(nan_features)})."
        )

    return features, float(base_28)
