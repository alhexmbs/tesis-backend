from sqlalchemy import Column, Date, Integer, Numeric

from app.database import Base


class TipoCambioBcrp(Base):
    """Tipo de cambio interbancario venta del BCRP (serie diaria PD04638PD). No depende del producto."""
    __tablename__ = "tipo_cambio_bcrp"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, nullable=False, unique=True, index=True)
    # nullable=True porque la serie diaria del BCRP trae "n.d." en feriados/días sin dato publicado
    tipo_cambio_venta = Column(Numeric(10, 4), nullable=True)
