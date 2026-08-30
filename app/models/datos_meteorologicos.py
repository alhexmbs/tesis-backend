from sqlalchemy import Column, Date, Integer, Numeric

from app.database import Base


class DatoMeteorologico(Base):
    """Clima diario (Open-Meteo). No depende del producto."""

    __tablename__ = "datos_meteorologicos"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, nullable=False, unique=True, index=True)
    temperatura_max = Column(Numeric(5, 2), nullable=True)
    temperatura_min = Column(Numeric(5, 2), nullable=True)
    precipitacion_mm = Column(Numeric(6, 2), nullable=True)
