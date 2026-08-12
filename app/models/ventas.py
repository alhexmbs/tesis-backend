from datetime import UTC, datetime

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String

from app.database import Base


class VentaHistorica(Base):
    __tablename__ = "ventas_historicas"

    id = Column(Integer, primary_key=True, index=True)

    fecha = Column(Date, nullable=False, index=True)
    producto = Column(String, nullable=False, index=True)

    # Variable objetivo y precios
    cantidad = Column(Numeric(10, 2), nullable=False)
    precio_promedio = Column(Numeric(10, 2), nullable=False)

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
    # Se permiten nulos (nullable=True) por si los primeros días no tienen historial
    ventas_hace_1_dia = Column(Numeric(10, 2), nullable=True)
    ventas_hace_2_dias = Column(Numeric(10, 2), nullable=True)
    ventas_hace_7_dias = Column(Numeric(10, 2), nullable=True)
    promedio_ultimos_3_dias = Column(Numeric(10, 2), nullable=True)
    promedio_ultimos_7_dias = Column(Numeric(10, 2), nullable=True)


class Prediccion(Base):
    __tablename__ = "predicciones"

    id = Column(Integer, primary_key=True, index=True)
    fecha_objetivo = Column(Date, nullable=False, index=True)
    producto = Column(String, nullable=False, index=True)
    cantidad_predicha = Column(Numeric(10, 2), nullable=False)
    fecha_creacion = Column(DateTime, default=lambda: datetime.now(UTC))


class IndiceBcrp(Base):
    __tablename__ = "indice_bcrp"

    id = Column(Integer, primary_key=True, index=True)
    producto = Column(String, nullable=False, index=True)
    fecha = Column(DateTime, default=lambda: datetime.now(UTC))
    indice_precio = Column(Numeric(10, 2), nullable=False)
