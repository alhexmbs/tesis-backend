from sqlalchemy import Column, Date, Integer, Numeric, String, UniqueConstraint

from app.database import Base


class PrecioCombustibleBcrp(Base):
    """Índice de precio de combustible del BCRP, ya empalmado (90/95 octanos -> Regular/Premium). Mensual, por producto."""

    __tablename__ = "precio_combustible_bcrp"
    __table_args__ = (
        UniqueConstraint(
            "fecha", "producto", name="uq_precio_combustible_fecha_producto"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, nullable=False, index=True)  # primer día del mes
    producto = Column(String, nullable=False, index=True)
    precio_combustible_bcrp = Column(Numeric(12, 6), nullable=False)
