"""Ingesta del reporte mensual de ventas (.xlsx) hacia ``historial_ventas``.

Es la ÚNICA vía por la que entran datos al sistema: el negocio ya tiene su propio
sistema transaccional, aquí solo se carga el reporte mensual que este exporta. No se
registran ventas una a una.

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

import pandas as pd
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


def _ultimo_valor_conocido(
    db: Session, producto: str, fecha_limite
) -> tuple[float | None, float | None]:
    """(precio_promedio, proporcion) del último día guardado ANTES de ``fecha_limite``."""
    registro = (
        db.query(HistorialVenta)
        .filter(HistorialVenta.producto == producto, HistorialVenta.fecha < fecha_limite)
        .order_by(HistorialVenta.fecha.desc())
        .first()
    )
    if registro is None:
        return None, None
    return (
        float(registro.precio_promedio),
        float(registro.proporcion_transacciones_grandes),
    )


def ingerir_ventas_mensuales(db: Session, contenido: bytes) -> dict:
    """Procesa un .xlsx de ventas y hace upsert por (fecha, producto).

    Es idempotente: subir dos veces el mismo mes actualiza las filas en vez de
    duplicarlas, y volver a subir un mes ya cargado corrige lo que hubiera cambiado.

    Returns
    -------
    dict con ``filas_guardadas``, ``filas_omitidas``, ``fecha_inicio``, ``fecha_fin``,
    ``productos`` y ``dias_sin_ventas`` (días-producto que el reporte no registró y que
    se guardaron como cero real, no como hueco).
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

    df = df[["fecha", "producto", *COLUMNAS_CRUDAS]].sort_values(["producto", "fecha"])
    dias_sin_ventas = int((df["n_transacciones_totales"] == 0).sum())

    fecha_min = df["fecha"].min().date()
    fecha_max = df["fecha"].max().date()

    # --- Arrastre del precio y de la proporción en los días sin ventas ---
    partes = []
    for producto, grupo in df.groupby("producto", sort=False):
        grupo = grupo.sort_values("fecha").copy()
        precio_previo, prop_previa = _ultimo_valor_conocido(db, producto, fecha_min)
        semilla = {"precio_promedio": precio_previo, "proporcion_transacciones_grandes": prop_previa}
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

    # --- Upsert ---
    # Se traen de una sola consulta las filas ya existentes del rango, en vez de un
    # SELECT por fila: cargar el histórico completo son miles de filas.
    existentes = {
        (r.fecha, r.producto): r
        for r in db.query(HistorialVenta)
        .filter(
            HistorialVenta.fecha >= fecha_min,
            HistorialVenta.fecha <= fecha_max,
            HistorialVenta.producto.in_(PRODUCTOS_SERVIDOS),
        )
        .all()
    }

    for fila in df.itertuples(index=False):
        fecha = fila.fecha.date()
        registro = existentes.get((fecha, fila.producto))
        if registro is None:
            registro = HistorialVenta(fecha=fecha, producto=fila.producto)
            db.add(registro)

        # cantidad negativa: un día cuyas notas de crédito superan las ventas. Se trunca
        # en 0 porque la tabla representa galones despachados, no el saldo contable.
        registro.cantidad = max(float(fila.cantidad), 0.0)
        registro.precio_promedio = float(fila.precio_promedio)
        registro.n_transacciones_totales = int(fila.n_transacciones_totales)
        registro.proporcion_transacciones_grandes = float(
            fila.proporcion_transacciones_grandes
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
