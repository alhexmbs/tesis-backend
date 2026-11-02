"""
Ingesta del reporte mensual de ventas (.xlsx) hacia la base de datos en 
    historial_ventas


Cadena: ``.xlsx`` -> :func:`extraer_excel` (transacciones) -> :func:`limpiar_datos`
(agregado diario x producto) -> las cuatro columnas crudas de ``historial_ventas``.
Ese agregado diario es exactamente el que produjo ``dataframe.ipynb`` para entrenar
el modelo, y ``tests/test_ingesta_xlsx.py`` lo comprueba contra ``df_diario.parquet``.



Sobre el arrastre de precio: ``limpiar_datos`` deja ``precio_promedio`` y
``proporcion_transacciones_grandes`` en NA los días sin ninguna venta (no hubo un
precio real ese día). Como las columnas de la tabla son NOT NULL, aquí se arrastra el
último valor conocido (ffill), primero dentro del propio lote y, para los primeros
días, desde lo que ya está guardado en la base. Es el mismo ffill que
``features.py`` aplicaría en tiempo de predicción, así que el resultado no cambia.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.historial import HistorialVenta
from app.services.prediccion.agregacion import limpiar_datos
from app.services.prediccion.extraccion import extraer_excel

logger = logging.getLogger(__name__)

# Solo se sirven estos tres. BIODIESEL se excluyó del modelo (en holdout quedó peor
# que el naive estacional), así que tampoco se guarda su historial.
PRODUCTOS_SERVIDOS = ("REGULAR", "PREMIUM", "GLP")

COLUMNAS_CRUDAS = (
    "cantidad",
    "precio_promedio",
    "n_transacciones_totales",
    "proporcion_transacciones_grandes",
)

# Columnas que se arrastran cuando el día no tuvo ninguna venta.
COLUMNAS_ARRASTRE = ("precio_promedio", "proporcion_transacciones_grandes")


class ArchivoInvalido(ValueError):
    """El archivo subido no es un reporte de ventas utilizable."""


class VentasYaRegistradas(ArchivoInvalido):
    """El reporte trae fechas que ya están en el historial.

    Las ventas registradas no se sobrescriben desde la carga: el reporte llega ya
    revisado por el área contable, y una corrección posterior la hace el administrador
    del sistema. Hereda de ArchivoInvalido para que la UI y el router la muestren
    como cualquier otro rechazo del archivo.
    """


class HuecoEnHistorial(ArchivoInvalido):
    """El reporte no empieza el día siguiente al último registrado.

    Si entrara (p. ej. diciembre cuando el historial llega al 30 de septiembre),
    octubre y noviembre quedarían vacíos y el modelo calcularía rezagos y promedios
    sobre días que faltan.
    """


_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def _fecha_larga(d: date) -> str:
    return f"{d.day} de {_MESES[d.month - 1]} de {d.year}"


def ultimo_dia_registrado(db: Session) -> date | None:
    """Último día guardado en el historial (de cualquiera de los tres productos)."""
    return (
        db.query(func.max(HistorialVenta.fecha))
        .filter(HistorialVenta.producto.in_(PRODUCTOS_SERVIDOS))
        .scalar()
    )


def _ultimo_valor_conocido(
    db: Session, producto: str, fecha_limite
) -> tuple[float | None, float | None]:
    """(precio_promedio, proporcion) del último día guardado ANTES de ``fecha_limite``."""
    registro = (
        db.query(HistorialVenta)
        .filter(
            HistorialVenta.producto == producto, HistorialVenta.fecha < fecha_limite
        )
        .order_by(HistorialVenta.fecha.desc())
        .first()
    )
    if registro is None:
        return None, None
    return (
        float(registro.precio_promedio),
        float(registro.proporcion_transacciones_grandes),
    )


def leer_reporte(contenido: bytes) -> pd.DataFrame:
    """Lee un .xlsx y devuelve su agregado diario x producto (sin tocar la base).

    Separado de :func:`guardar_reporte` para que la UI pueda leer varios archivos,
    ordenarlos por la fecha real de su contenido y guardarlos en orden.
    """
    try:
        transacciones = extraer_excel(contenido)
    except ValueError:
        raise
    except Exception as e:  # openpyxl, formato de fecha, archivo corrupto...
        raise ArchivoInvalido(f"No se pudo leer el archivo .xlsx: {e}") from e

    df = limpiar_datos(transacciones)
    df = df[df["producto"].isin(PRODUCTOS_SERVIDOS)].copy()
    if df.empty:
        raise ArchivoInvalido(
            "El archivo no contiene ventas de REGULAR, PREMIUM ni GLP."
        )
    return df[["fecha", "producto", *COLUMNAS_CRUDAS]].sort_values(
        ["producto", "fecha"]
    )


def ingerir_ventas_mensuales(db: Session, contenido: bytes) -> dict:
    """Lee un .xlsx de ventas y guarda sus días en el historial (un solo archivo)."""
    return guardar_reporte(db, leer_reporte(contenido))


def guardar_reporte(db: Session, df: pd.DataFrame) -> dict:
    """Guarda en el historial el agregado diario de un reporte ya leído.

    Solo agrega días nuevos: si el reporte trae alguna fecha que ya está registrada,
    se rechaza el archivo completo (``VentasYaRegistradas``) y no se guarda nada.
    Así un archivo entra entero o no entra, y las ventas ya cargadas no cambian.
    Además el reporte debe empezar justo el día siguiente al último registrado
    (``HuecoEnHistorial``): el historial no puede quedar con días vacíos.

    Returns
    -------
    dict con ``filas_guardadas``, ``filas_omitidas``, ``fecha_inicio``, ``fecha_fin``,
    ``productos`` y ``dias_sin_ventas`` (días-producto que el reporte no registró y que
    se guardaron como cero real, no como hueco).
    """
    dias_sin_ventas = int((df["n_transacciones_totales"] == 0).sum())

    fecha_min = df["fecha"].min().date()
    fecha_max = df["fecha"].max().date()

    # --- Rechazo de fechas ya registradas ---
    # Se revisa antes de procesar nada: basta un día-producto ya guardado para
    # rechazar el archivo entero.
    ya_registradas = (
        db.query(HistorialVenta.fecha)
        .filter(
            HistorialVenta.fecha >= fecha_min,
            HistorialVenta.fecha <= fecha_max,
            HistorialVenta.producto.in_(PRODUCTOS_SERVIDOS),
        )
        .distinct()
        .count()
    )
    if ya_registradas:
        raise VentasYaRegistradas(
            f"Las ventas de este periodo ya están registradas ({ya_registradas} "
            f"día(s) entre el {fecha_min:%d/%m/%Y} y el {fecha_max:%d/%m/%Y}). "
            "No se guardó nada. Si el reporte tiene correcciones, contacta al "
            "administrador del sistema."
        )

    # --- Rechazo de huecos ---
    # El reporte debe continuar el historial sin saltarse días.
    ultimo = ultimo_dia_registrado(db)
    if ultimo is not None:
        siguiente = ultimo + timedelta(days=1)
        if fecha_min != siguiente:
            raise HuecoEnHistorial(
                f"El último día registrado es el {_fecha_larga(ultimo)}. Sube el "
                f"reporte a partir del {_fecha_larga(siguiente)} para no dejar días "
                "vacíos en el historial. No se guardó nada."
            )

    # --- Arrastre del precio y de la proporción en los días sin ventas ---
    partes = []
    for producto, grupo in df.groupby("producto", sort=False):
        grupo = grupo.sort_values("fecha").copy()
        precio_previo, prop_previa = _ultimo_valor_conocido(db, producto, fecha_min)
        semilla = {
            "precio_promedio": precio_previo,
            "proporcion_transacciones_grandes": prop_previa,
        }
        for columna in COLUMNAS_ARRASTRE:
            grupo[columna] = grupo[columna].astype("float64").ffill()
            if semilla[columna] is not None:
                grupo[columna] = grupo[columna].fillna(semilla[columna])
        partes.append(grupo)
    df = pd.concat(partes, ignore_index=True)

    # Filas que quedan sin precio son las del arranque absoluto del historial (días sin
    # ventas y sin ningún día anterior del que arrastrar). No se pueden guardar porque
    # la tabla es NOT NULL, y tampoco tendría sentido inventarles un precio.
    sin_precio = df[list(COLUMNAS_ARRASTRE)].isna().any(axis=1)
    filas_omitidas = int(sin_precio.sum())
    df = df[~sin_precio]

    # --- Inserción ---
    # Todas las filas son nuevas: las fechas ya registradas se rechazaron arriba.
    for fila in df.itertuples(index=False):
        db.add(
            HistorialVenta(
                fecha=fila.fecha.date(),
                producto=fila.producto,
                # cantidad negativa: un día cuyas notas de crédito superan las ventas.
                # Se trunca en 0 porque la tabla representa galones despachados, no
                # el saldo contable.
                cantidad=max(float(fila.cantidad), 0.0),
                precio_promedio=float(fila.precio_promedio),
                n_transacciones_totales=int(fila.n_transacciones_totales),
                proporcion_transacciones_grandes=float(
                    fila.proporcion_transacciones_grandes
                ),
            )
        )

    db.commit()

    logger.info(
        "Ingesta de ventas: %s filas de %s a %s (%s omitidas).",
        len(df),
        fecha_min,
        fecha_max,
        filas_omitidas,
    )
    return {
        "filas_guardadas": len(df),
        "filas_omitidas": filas_omitidas,
        "fecha_inicio": fecha_min,
        "fecha_fin": fecha_max,
        "productos": sorted(df["producto"].unique().tolist()),
        "dias_sin_ventas": dias_sin_ventas,
    }
