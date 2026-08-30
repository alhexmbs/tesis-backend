from sqlalchemy import Column, Date, Integer, Numeric, String, UniqueConstraint

from app.database import Base


class VentaHistorica(Base):
    __tablename__ = "ventas_historicas"
    __table_args__ = (UniqueConstraint("fecha", "producto", name="uq_ventas_fecha_producto"),)

    id = Column(Integer, primary_key=True, index=True)

    fecha = Column(Date, nullable=False, index=True)
    producto = Column(String, nullable=False, index=True)

    # Variable objetivo y precios
    cantidad = Column(Numeric(10, 2), nullable=False)
    precio_promedio = Column(Numeric(10, 2), nullable=False)

    # Variables macro (fusionadas desde las tablas de staging en construir_dataset_modelo)
    precio_wti_usd = Column(Numeric(10, 4), nullable=True)
    precio_combustible_bcrp = Column(Numeric(12, 6), nullable=True)
    tipo_cambio_venta = Column(Numeric(10, 4), nullable=True)
    temperatura_max = Column(Numeric(5, 2), nullable=True)
    temperatura_min = Column(Numeric(5, 2), nullable=True)
    precipitacion_mm = Column(Numeric(6, 2), nullable=True)

    # Variables booleanas / banderas temporales (0 o 1)
    feriado = Column(Integer, default=0)
    fin_de_semana = Column(Integer, default=0)
    es_vispera_navidad = Column(Integer, default=0)
    es_vispera_year_nuevo = Column(Integer, default=0)
    es_vispera_semana_santa = Column(Integer, default=0)
    es_vispera_feriado_general = Column(Integer, default=0)

    # Variables de calendario
    year = Column(Integer, nullable=False)
    mes = Column(Integer, nullable=False)
    dia = Column(Integer, nullable=False)
    dia_semana = Column(Integer, nullable=False)
    semana = Column(Integer, nullable=False)
    trimestre = Column(Integer, nullable=False)
    dia_del_year = Column(Integer, nullable=False)

    # Variables de rezago (Lags) y tendencias (promedios móviles)
    ventas_hace_1_dia = Column(Numeric(10, 2), nullable=True)
    ventas_hace_2_dias = Column(Numeric(10, 2), nullable=True)
    ventas_hace_7_dias = Column(Numeric(10, 2), nullable=True)
    promedio_ultimos_3_dias = Column(Numeric(10, 2), nullable=True)
    promedio_ultimos_7_dias = Column(Numeric(10, 2), nullable=True)