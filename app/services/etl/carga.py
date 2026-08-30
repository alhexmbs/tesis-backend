from datetime import date, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from app.models.datos_meteorologicos import DatoMeteorologico
from app.models.indice_precio_combustibles import PrecioCombustibleBcrp
from app.models.precio_wti import PrecioWti
from app.models.tipo_cambio import TipoCambioBcrp
from app.models.ventas import VentaHistorica


def _a_float(valor):
    """Convierte NaN/None a None y cualquier número (incluido numpy.float64) a float nativo de Python."""
    if valor is None or pd.isna(valor):
        return None
    return float(valor)


def _a_entero(valor):
    """Convierte NaN/None a None y cualquier número (incluido numpy.int64/bool_) a int nativo de Python."""
    if valor is None or pd.isna(valor):
        return None
    return int(valor)


def guardar_precio_wti(db: Session, df: pd.DataFrame) -> None:
    """Guarda el precio spot del WTI: busca el registro por fecha, si existe lo actualiza, si no, lo crea."""
    for _, fila in df.iterrows():
        fecha = pd.Timestamp(fila["fecha"]).date()

        registro = db.query(PrecioWti).filter(PrecioWti.fecha == fecha).first()
        if registro is None:
            registro = PrecioWti(fecha=fecha)
            db.add(registro)

        registro.precio_wti_usd = _a_float(fila["precio_wti_usd"])

    db.commit()


def guardar_tipo_cambio(db: Session, df: pd.DataFrame) -> None:
    """Guarda el tipo de cambio del BCRP: busca el registro por fecha, si existe lo actualiza, si no, lo crea."""
    for _, fila in df.iterrows():
        fecha = pd.Timestamp(fila["fecha"]).date()

        registro = (
            db.query(TipoCambioBcrp).filter(TipoCambioBcrp.fecha == fecha).first()
        )
        if registro is None:
            registro = TipoCambioBcrp(fecha=fecha)
            db.add(registro)

        registro.tipo_cambio_venta = _a_float(fila["valor"])

    db.commit()


def guardar_datos_meteorologicos(db: Session, df: pd.DataFrame) -> None:
    """Guarda el clima diario: busca el registro por fecha, si existe lo actualiza, si no, lo crea."""
    for _, fila in df.iterrows():
        fecha = pd.Timestamp(fila["fecha"]).date()

        registro = (
            db.query(DatoMeteorologico).filter(DatoMeteorologico.fecha == fecha).first()
        )
        if registro is None:
            registro = DatoMeteorologico(fecha=fecha)
            db.add(registro)

        registro.temperatura_max = _a_float(fila["temperatura_max"])
        registro.temperatura_min = _a_float(fila["temperatura_min"])
        registro.precipitacion_mm = _a_float(fila["precipitacion_mm"])

    db.commit()


def guardar_indice_precio_combustibles(db: Session, df: pd.DataFrame) -> None:
    """Guarda el índice de precio de combustible del BCRP: busca el registro por fecha y producto, si existe lo actualiza, si no, lo crea."""
    for _, fila in df.iterrows():
        fecha = pd.Timestamp(fila["fecha"]).date()
        producto = fila["producto"]

        registro = (
            db.query(PrecioCombustibleBcrp)
            .filter(
                PrecioCombustibleBcrp.fecha == fecha,
                PrecioCombustibleBcrp.producto == producto,
            )
            .first()
        )
        if registro is None:
            registro = PrecioCombustibleBcrp(fecha=fecha, producto=producto)
            db.add(registro)

        registro.precio_combustible_bcrp = _a_float(fila["precio_combustible_bcrp"])

    db.commit()


def guardar_ventas_historicas(db: Session, df: pd.DataFrame) -> None:
    """Guarda el dataset final de ventas (calendario, rezagos y variables macro ya calculadas):
    busca el registro por fecha y producto, si existe lo actualiza, si no, lo crea."""
    for _, fila in df.iterrows():
        fecha = pd.Timestamp(fila["fecha"]).date()
        producto = fila["producto"]

        registro = (
            db.query(VentaHistorica)
            .filter(VentaHistorica.fecha == fecha, VentaHistorica.producto == producto)
            .first()
        )
        if registro is None:
            registro = VentaHistorica(fecha=fecha, producto=producto)
            db.add(registro)

        registro.cantidad = _a_float(fila["cantidad"])
        registro.precio_promedio = _a_float(fila["precio_promedio"])

        registro.feriado = _a_entero(fila["feriado"])
        registro.fin_de_semana = _a_entero(fila["fin_de_semana"])
        registro.es_vispera_navidad = _a_entero(fila["es_vispera_navidad"])
        registro.es_vispera_year_nuevo = _a_entero(fila["es_vispera_year_nuevo"])
        registro.es_vispera_semana_santa = _a_entero(fila["es_vispera_semana_santa"])
        registro.es_vispera_feriado_general = _a_entero(
            fila["es_vispera_feriado_general"]
        )

        registro.year = _a_entero(fila["year"])
        registro.mes = _a_entero(fila["mes"])
        registro.dia = _a_entero(fila["dia"])
        registro.dia_semana = _a_entero(fila["dia_semana"])
        registro.semana = _a_entero(fila["semana"])
        registro.trimestre = _a_entero(fila["trimestre"])
        registro.dia_del_year = _a_entero(fila["dia_del_year"])

        registro.ventas_hace_1_dia = _a_float(fila["ventas_hace_1_dia"])
        registro.ventas_hace_2_dias = _a_float(fila["ventas_hace_2_dias"])
        registro.ventas_hace_7_dias = _a_float(fila["ventas_hace_7_dias"])
        registro.promedio_ultimos_3_dias = _a_float(fila["promedio_ultimos_3_dias"])
        registro.promedio_ultimos_7_dias = _a_float(fila["promedio_ultimos_7_dias"])

        registro.precio_wti_usd = _a_float(fila["precio_wti_usd"])
        registro.precio_combustible_bcrp = _a_float(fila["precio_combustible_bcrp"])
        registro.tipo_cambio_venta = _a_float(fila["tipo_cambio_venta"])
        registro.temperatura_max = _a_float(fila["temperatura_max"])
        registro.temperatura_min = _a_float(fila["temperatura_min"])
        registro.precipitacion_mm = _a_float(fila["precipitacion_mm"])

    db.commit()


def obtener_historico_para_lags(
    db: Session, fecha_inicio: date, productos: list[str]
) -> list[dict]:
    """
    Trae los últimos días de ventas ya guardados antes de fecha_inicio, por producto,
    para que feature_engineering pueda calcular lags/promedios del nuevo lote sin
    perder los primeros ~7 días del mes que se está subiendo.
    """
    fecha_desde = fecha_inicio - timedelta(days=10)  # margen extra por si hay huecos
    registros = (
        db.query(VentaHistorica)
        .filter(VentaHistorica.producto.in_(productos))
        .filter(VentaHistorica.fecha >= fecha_desde)
        .filter(VentaHistorica.fecha < fecha_inicio)
        .order_by(VentaHistorica.producto, VentaHistorica.fecha)
        .all()
    )
    return [
        {"fecha": r.fecha, "producto": r.producto, "cantidad": float(r.cantidad)}
        for r in registros
    ]
