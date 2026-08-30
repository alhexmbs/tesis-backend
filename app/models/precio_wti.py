from sqlalchemy import Column, Date, Integer, Numeric

from app.database import Base


class PrecioWti(Base):
    """Precio spot internacional del WTI (EIA). Diario, no depende del producto."""

    __tablename__ = "precio_wti"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, nullable=False, unique=True, index=True)
    precio_wti_usd = Column(Numeric(10, 4), nullable=False)
