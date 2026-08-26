from datetime import UTC, datetime

from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String

from app.database import Base


class Prediccion(Base):
    __tablename__ = "predicciones"

    id = Column(Integer, primary_key=True, index=True)
    fecha_objetivo = Column(Date, nullable=False, index=True)
    producto = Column(String, nullable=False, index=True)
    cantidad_predicha = Column(Numeric(10, 2), nullable=False)
    fecha_creacion = Column(DateTime, default=lambda: datetime.now(UTC))