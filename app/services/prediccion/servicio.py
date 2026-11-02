"""Servicio de predicción de demanda: carga de artefactos, features desde BD,
predicción en galones, predicción de rango recursiva e historial.

Los artefactos (3 modelos .joblib + config_servicio.json) se cargan UNA sola vez
al arrancar la app (ver ``cargar_artefactos``, llamado desde el lifespan de
FastAPI en ``app/main.py``).

Reconstrucción: ``prediccion = max(modelo.predict(features) * base_28, 0)``. Las
features se construyen en ``features.py`` (copia fiel del notebook). El único dato
crudo que alimenta la inferencia vive en la tabla ``historial_ventas``.

El reporte de ventas llega con retraso, así que la fecha pedida suele quedar varios
días por delante del último día cargado. Ese hueco se PUENTEA con predicciones
recursivas (``_puentear_historial``); nunca se rellena con ceros, que falsearían
base_28 y dejarían ``cantidad_cv_7`` en NaN. El horizonte total está topado en
``MAX_HORIZONTE_DIAS`` días desde el final del historial real.

El precio del día no es un parámetro de entrada: el régimen de precios entra
congelado al modelo, así que no hay escenarios "¿y si subo el precio?"; siempre se
arrastra el último precio registrado.
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass
from datetime import date, timedelta

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import CONFIG_SERVICIO_PATH, MODELOS_DIR, VERIFICACION_PATH
from app.models.historial import HistorialVenta
from app.services.prediccion.clima import obtener_temperatura_max
from app.services.prediccion.features import (
    COLUMNAS_HISTORIAL,
    HistorialInsuficiente,
    calcular_features_dia,
)

logger = logging.getLogger(__name__)


class ProductoNoServido(ValueError):
    """Se pidió un producto fuera de los 3 servidos (REGULAR, PREMIUM, GLP)."""


class FechaEnPasado(ValueError):
    """Se pidió una predicción para un día que ya ocurrió.

    Pronosticar hacia atrás no tiene sentido de negocio: ese día ya se vendió y el
    dato real vive (o vivirá, al cargar el reporte) en el historial. Se valida en el
    servicio y no en el schema de Pydantic porque hay dos entradas a la predicción:
    el router `/api/prediccion` y la UI de Gradio, que llama al servicio directo.
    """


@dataclass
class Artefactos:
    config: dict
    modelos: dict  # producto -> sklearn Pipeline

    @property
    def productos(self) -> list[str]:
        return self.config["productos"]

    @property
    def orden_features(self) -> list[str]:
        return self.config["features"]

    @property
    def regimen(self) -> dict:
        return self.config["regimen_precio_congelado"]


_artefactos: Artefactos | None = None


def cargar_artefactos() -> Artefactos:
    """Carga config + los 3 modelos una sola vez. Se llama desde el lifespan."""
    global _artefactos
    with open(CONFIG_SERVICIO_PATH, encoding="utf-8") as f:
        config = json.load(f)

    modelos = {}
    with warnings.catch_warnings():
        # Los .joblib se serializaron con sklearn 1.3.1; StandardScaler+Ridge es
        # aritmética estable entre versiones (lo prueba el test de equivalencia).
        warnings.simplefilter("ignore")
        for producto in config["productos"]:
            modelos[producto] = joblib.load(MODELOS_DIR / f"{producto}.joblib")

    _artefactos = Artefactos(config=config, modelos=modelos)
    logger.info(
        "Artefactos de predicción cargados: %s modelos (%s).",
        len(modelos),
        ", ".join(config["productos"]),
    )
    return _artefactos


def obtener_artefactos() -> Artefactos:
    if _artefactos is None:
        cargar_artefactos()
    assert _artefactos is not None
    return _artefactos


def _validar_producto(producto: str, art: Artefactos) -> None:
    if producto not in art.productos:
        raise ProductoNoServido(
            f"Producto '{producto}' no disponible. Productos servidos: "
            f"{', '.join(art.productos)}."
        )


def _validar_fecha_futura(fecha: date, etiqueta: str = "La fecha") -> None:
    """Rechaza las fechas anteriores a hoy. Hoy sí se permite: el día aún no cierra."""
    hoy = date.today()
    if fecha < hoy:
        raise FechaEnPasado(
            f"{etiqueta} {fecha} ya pasó. El sistema solo pronostica de hoy ({hoy}) "
            "en adelante; para ver lo que se vendió ese día, revisa el historial."
        )


def _historial_df(db: Session, producto: str) -> pd.DataFrame:
    """Historial crudo del producto (fecha + columnas crudas), ordenado por fecha."""
    registros = (
        db.query(HistorialVenta)
        .filter(HistorialVenta.producto == producto)
        .order_by(HistorialVenta.fecha)
        .all()
    )
    return pd.DataFrame(
        [
            {
                "fecha": r.fecha,
                "cantidad": float(r.cantidad),
                "precio_promedio": float(r.precio_promedio),
                "n_transacciones_totales": int(r.n_transacciones_totales),
                "proporcion_transacciones_grandes": float(
                    r.proporcion_transacciones_grandes
                ),
            }
            for r in registros
        ],
        columns=["fecha", *COLUMNAS_HISTORIAL],
    )


def _predecir(art: Artefactos, producto: str, features: dict, base_28: float) -> float:
    # DataFrame con nombres de columna en el orden de entrenamiento: evita el
    # warning de sklearn y garantiza el orden correcto de las 17 features.
    X = pd.DataFrame(
        [[features[n] for n in art.orden_features]], columns=art.orden_features
    )
    razon = float(art.modelos[producto].predict(X)[0])
    return max(razon * base_28, 0.0)


# El reporte de ventas llega con semanas de retraso, así que casi siempre quedan
# días sin cargar entre el final del historial y la fecha pedida. Esos días se
# estiman con el propio modelo, pero solo hasta este horizonte: más allá la
# proyección deja de ser un apoyo útil para decidir la compra de combustible.
MAX_HORIZONTE_DIAS = 37  # TEMPORAL para pruebas: el valor real es 15

NOTA_ESTIMACION = (
    "Le recomendamos mantener actualizado el registro de ventas para obtener una "
    "predicción más precisa."
)

NOTA_HORIZONTE = (
    "Se ajustó el rango a {dias} día(s): el sistema proyecta como máximo "
    "{maximo} días desde el último día con ventas registradas ({ultimo_real})."
)


def _con_dia_predicho(
    hist: pd.DataFrame,
    fecha: date,
    galones: float,
    precio: float,
    n_trans: int,
    prop_grandes: float,
) -> pd.DataFrame:
    """Añade al historial un día PREDICHO (no real) para poder seguir la recursión.

    Solo se predice ``cantidad``; el precio y las variables internas del día se
    arrastran del último día real, porque el modelo no las pronostica.
    """
    return pd.concat(
        [
            hist,
            pd.DataFrame(
                [
                    {
                        "fecha": pd.Timestamp(fecha),
                        "cantidad": galones,
                        "precio_promedio": precio,
                        "n_transacciones_totales": n_trans,
                        "proporcion_transacciones_grandes": prop_grandes,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )


def _horizonte(previos: pd.DataFrame, fecha: date) -> tuple[date, int]:
    """(último día con ventas reales, días que lo separan de ``fecha``)."""
    ultimo_real = pd.Timestamp(previos["fecha"].max()).date()
    return ultimo_real, (pd.Timestamp(fecha).date() - ultimo_real).days


def _validar_horizonte(
    producto: str, ultimo_real: date, fecha: date, dias: int
) -> None:
    """Corta las fechas demasiado lejos del último día con ventas cargadas.

    Sin ventas que refresquen la serie, cada día extra se apoya en estimaciones del
    día anterior; pasado ``MAX_HORIZONTE_DIAS`` la proyección deja de ser útil.
    """
    if dias > MAX_HORIZONTE_DIAS:
        raise HistorialInsuficiente(
            f"La fecha {fecha} queda {dias} días después del último día con ventas "
            f"registradas de {producto} ({ultimo_real}). El sistema proyecta como "
            f"máximo {MAX_HORIZONTE_DIAS} días: carga el reporte de ventas más reciente."
        )


def _puentear_historial(
    art: Artefactos,
    producto: str,
    previos: pd.DataFrame,
    fecha_objetivo: date,
) -> tuple[pd.DataFrame, list[date]]:
    """Rellena el HUECO entre el final del historial real y ``fecha_objetivo``.

    Sin este puente, los días sin cargar entrarían al calendario diario de
    ``features.py`` como ceros (un hueco no es lo mismo que un día sin ventas):
    base_28 quedaría contaminada y, con 7 ceros seguidos, ``cantidad_cv_7`` sería
    0/0 = NaN y la predicción fallaría.

    Cada día del hueco se predice y se incorpora al historial, igual que en
    ``predecir_rango``. Devuelve (historial aumentado, días estimados).
    """
    ultimo_real, horizonte = _horizonte(previos, fecha_objetivo)
    hueco = horizonte - 1
    if hueco <= 0:
        return previos.copy(), []
    _validar_horizonte(producto, ultimo_real, fecha_objetivo, horizonte)

    ultimo = previos.iloc[-1]
    precio_arrastre = float(ultimo["precio_promedio"])
    n_trans_arrastre = int(ultimo["n_transacciones_totales"])
    prop_arrastre = float(ultimo["proporcion_transacciones_grandes"])

    hist_aug = previos.copy()
    estimados: list[date] = []
    for i in range(hueco):
        fecha = ultimo_real + timedelta(days=i + 1)
        temp, _ = obtener_temperatura_max(fecha)
        features, base_28 = calcular_features_dia(
            historial_previo=hist_aug,
            fecha=fecha,
            temperatura_max=temp,
            regimen_precio=int(art.regimen[producto]),
        )
        galones = _predecir(art, producto, features, base_28)
        hist_aug = _con_dia_predicho(
            hist_aug, fecha, galones, precio_arrastre, n_trans_arrastre, prop_arrastre
        )
        estimados.append(fecha)

    logger.info(
        "Estimados %s días sin ventas reales de %s (%s a %s) para poder predecir.",
        len(estimados),
        producto,
        estimados[0],
        estimados[-1],
    )
    return hist_aug, estimados


def predecir_dia(
    db: Session,
    producto: str,
    fecha: date,
    temperatura_max: float | None = None,
) -> dict:
    """Predice los galones de un día. Devuelve galones + features + metadatos.

    El precio del día NO se pide: el modelo no es un modelo de elasticidad-precio
    (el régimen de precios entra congelado, ver ``config_servicio.json``), así que
    siempre se arrastra el último precio registrado. Se devuelve como
    ``precio_referencia``, solo informativo.

    ``temperatura_max`` (opcional): si no se pasa, se pide el pronóstico de Open-Meteo.

    Solo se predice de hoy en adelante: una fecha ya pasada lanza ``FechaEnPasado``.
    """
    art = obtener_artefactos()
    _validar_producto(producto, art)
    _validar_fecha_futura(fecha)

    hist = _historial_df(db, producto)
    previos = hist[pd.to_datetime(hist["fecha"]) < pd.Timestamp(fecha)]
    if previos.empty:
        raise HistorialInsuficiente(
            f"No hay historial de {producto} anterior a {fecha} para predecir."
        )

    ultimo_real, horizonte = _horizonte(previos, fecha)
    _validar_horizonte(producto, ultimo_real, fecha, horizonte)
    precio_referencia = float(previos.iloc[-1]["precio_promedio"])

    if temperatura_max is not None:
        temp, fuente_temp = float(temperatura_max), "informado"
    else:
        temp, fuente_temp = obtener_temperatura_max(fecha)

    # Si el historial real no llega hasta la víspera de `fecha`, se estiman los días
    # intermedios en vez de dejar que se rellenen con ceros.
    hist_aug, estimados = _puentear_historial(art, producto, previos, fecha)

    features, base_28 = calcular_features_dia(
        historial_previo=hist_aug,
        fecha=fecha,
        temperatura_max=temp,
        regimen_precio=int(art.regimen[producto]),
    )
    galones = _predecir(art, producto, features, base_28)

    notas = []
    if estimados:
        notas.append(NOTA_ESTIMACION.format(ultimo_real=ultimo_real, n=len(estimados)))

    return {
        "producto": producto,
        "fecha": fecha,
        "prediccion_galones": round(galones, 2),
        "promedio_diario_28": round(base_28, 2),
        "precio_referencia": round(precio_referencia, 2),
        "temperatura_max": round(temp, 2),
        "fuente_temperatura": fuente_temp,
        "ultimo_dia_real": ultimo_real,
        "dias_estimados": len(estimados),
        "notas": notas,
        # Las 17 features quedan en la respuesta de la API (trazabilidad del modelo),
        # pero la UI del grifo no las muestra: no le dicen nada al usuario final.
        "features_usadas": features,
    }


def predecir_rango(
    db: Session,
    producto: str,
    fecha_inicio: date,
    dias: int,
) -> dict:
    """Predicción recursiva de ``dias`` días. Cada día predicho se incorpora al
    historial para calcular el siguiente.

    El rango se recorta para que el último día no pase de ``MAX_HORIZONTE_DIAS``
    días desde el final del historial real: sin ventas diarias que refresquen la
    serie, proyectar más lejos no aporta calidad. El recorte se informa en ``notas``.
    """
    art = obtener_artefactos()
    _validar_producto(producto, art)
    _validar_fecha_futura(fecha_inicio, "La fecha de inicio")

    hist = _historial_df(db, producto)
    previos = hist[pd.to_datetime(hist["fecha"]) < pd.Timestamp(fecha_inicio)]
    if previos.empty:
        raise HistorialInsuficiente(
            f"No hay historial de {producto} anterior a {fecha_inicio} para predecir."
        )

    ultimo_real, horizonte_inicio = _horizonte(previos, fecha_inicio)
    _validar_horizonte(producto, ultimo_real, fecha_inicio, horizonte_inicio)

    # Valores arrastrados del último día real para los días predichos.
    ultimo = previos.iloc[-1]
    precio_referencia = float(ultimo["precio_promedio"])
    n_trans_arrastre = int(ultimo["n_transacciones_totales"])
    prop_arrastre = float(ultimo["proporcion_transacciones_grandes"])

    # Recorte: el último día del rango no puede pasar de
    # ultimo_real + MAX_HORIZONTE_DIAS.
    dias_solicitados = int(dias)
    dias_max = max(1, MAX_HORIZONTE_DIAS - max(horizonte_inicio, 1) + 1)
    dias_efectivos = min(dias_solicitados, dias_max)

    # Se parte solo de la historia ANTERIOR a fecha_inicio: los días del rango se
    # predicen y se van incorporando. Cualquier dato real en/desde fecha_inicio se
    # ignora a propósito (es lo que se está pronosticando). Si el historial real no
    # llega hasta la víspera de fecha_inicio, el hueco se estima igual que en
    # predecir_dia.
    hist_aug, estimados = _puentear_historial(art, producto, previos, fecha_inicio)
    predicciones = []
    for i in range(dias_efectivos):
        fecha = fecha_inicio + timedelta(days=i)
        temp, fuente_temp = obtener_temperatura_max(fecha)

        features, base_28 = calcular_features_dia(
            historial_previo=hist_aug,
            fecha=fecha,
            temperatura_max=temp,
            regimen_precio=int(art.regimen[producto]),
        )
        galones = _predecir(art, producto, features, base_28)
        predicciones.append(
            {
                "fecha": fecha,
                "prediccion_galones": round(galones, 2),
                "temperatura_max": round(temp, 2),
                "fuente_temperatura": fuente_temp,
            }
        )

        # Incorporar el día predicho al historial para el siguiente.
        hist_aug = _con_dia_predicho(
            hist_aug, fecha, galones, precio_referencia, n_trans_arrastre, prop_arrastre
        )

    notas = []
    if estimados:
        notas.append(NOTA_ESTIMACION.format(ultimo_real=ultimo_real, n=len(estimados)))
    if dias_efectivos < dias_solicitados:
        notas.append(
            NOTA_HORIZONTE.format(
                dias=dias_efectivos,
                maximo=MAX_HORIZONTE_DIAS,
                ultimo_real=ultimo_real,
            )
        )

    return {
        "producto": producto,
        "fecha_inicio": fecha_inicio,
        "dias": dias_efectivos,
        "dias_solicitados": dias_solicitados,
        "precio_referencia": round(precio_referencia, 2),
        "predicciones": predicciones,
        "ultimo_dia_real": ultimo_real,
        "dias_estimados": len(estimados),
        "notas": notas,
    }


def ultimo_dia_historial(db: Session, producto: str) -> date | None:
    """Última fecha con ventas registradas del producto.

    La UI la usa para proponer como fecha por defecto el día siguiente al final del
    historial, en vez de "mañana" según el reloj: si el historial va por detrás del
    calendario, predecir mañana falla por falta de los 28 días previos.
    """
    registro = (
        db.query(HistorialVenta)
        .filter(HistorialVenta.producto == producto)
        .order_by(HistorialVenta.fecha.desc())
        .first()
    )
    return registro.fecha if registro else None


def venta_promedio_diaria(
    db: Session, producto: str, hasta: date, dias: int = 90
) -> float | None:
    """Galones vendidos por día, en promedio, en los ``dias`` días hasta ``hasta``.

    La UI lo pone al lado del error medio: 138 galones de error asustan, pero en un
    producto que vende ~2,900 galones al día son menos del 5 %.
    """
    desde = hasta - timedelta(days=dias - 1)
    cantidades = [
        float(r.cantidad)
        for r in db.query(HistorialVenta)
        .filter(
            HistorialVenta.producto == producto,
            HistorialVenta.fecha >= desde,
            HistorialVenta.fecha <= hasta,
        )
        .all()
    ]
    return sum(cantidades) / len(cantidades) if cantidades else None


def listar_historial(db: Session, producto: str) -> list[HistorialVenta]:
    art = obtener_artefactos()
    _validar_producto(producto, art)
    return (
        db.query(HistorialVenta)
        .filter(HistorialVenta.producto == producto)
        .order_by(HistorialVenta.fecha)
        .all()
    )


def metricas_modelo() -> dict:
    """Métricas de holdout del modelo servido, solo para REGULAR/PREMIUM/GLP.

    Toma los números de config_servicio.json (no escritos a mano) y, por producto,
    deriva el 'acierto' (100 - MAPE), el error medio en galones/día (MAE) y cuánto
    menos se equivoca que el método simple de "repetir lo que se vendió el mismo día
    de la semana pasada" (naive estacional, evaluado en los mismos 90 días).
    """
    art = obtener_artefactos()
    modelo = art.config["modelo"]  # "ridge"
    mae_naive = {
        m["producto"]: m["mae"]
        for m in art.config["metricas_holdout"]
        if m["modelo"] == "naive_estacional"
    }
    filas = []
    for m in art.config["metricas_holdout"]:
        if m["producto"] in art.productos and m["modelo"] == modelo:
            filas.append(
                {
                    "producto": m["producto"],
                    "acierto_pct": round(100 - m["mape"], 1),
                    "error_medio_galones": round(m["mae"], 0),
                    # 1 - MAE_modelo / MAE_naive: 20 = se equivoca 20 % menos.
                    "mejora_vs_simple_pct": round(
                        (1 - m["mae"] / mae_naive[m["producto"]]) * 100, 1
                    ),
                    "mape": round(m["mape"], 2),
                    "mae": round(m["mae"], 2),
                    "rmse": round(m["rmse"], 2),
                    "mase": round(m["mase"], 3),
                    "r2": round(m["r2"], 3),
                }
            )
    # Orden por acierto descendente (como en la pestaña de métricas de la UI).
    filas.sort(key=lambda x: x["acierto_pct"], reverse=True)
    return {
        "modelo": modelo,
        "fecha_entrenamiento": art.config["fecha_entrenamiento"],
        "metricas": filas,
    }

def verificacion_ultimo_mes(producto: str, desde: date, hasta: date) -> pd.DataFrame:
    """Real vs. predicho de septiembre 2026, del notebook de verificación
    (modelo entrenado hasta el 31/08, septiembre predicho en cadena sin ver ventas reales)."""
    t = pd.read_csv(VERIFICACION_PATH, parse_dates=["fecha"])
    t = t[(t["producto"] == producto)
          & (t["fecha"].dt.date >= desde) & (t["fecha"].dt.date <= hasta)]
    return t.sort_values("fecha")

def margen_error_galones(producto: str) -> float:
    """Margen ± en galones por día, sacado de la prueba de septiembre.

    Es el percentil 90 de |real − predicho|: en 27 de los 30 días de la prueba el
    error fue menor que este número. Se da en galones y no en %, porque el % exagera
    el error de los combustibles que venden poco (PREMIUM).
    """
    t = pd.read_csv(VERIFICACION_PATH)
    errores = t.loc[t["producto"] == producto, "real_menos_predicho"].abs()
    return float(errores.quantile(0.9)) if not errores.empty else 0.0
