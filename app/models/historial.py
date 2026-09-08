from sqlalchemy import Column, Date, Integer, Numeric, String, UniqueConstraint

from app.database import Base


class HistorialVenta(Base):
    """Historial diario de ventas por producto que ALIMENTA LA INFERENCIA.

    Junto con ``usuarios``, es una de las dos únicas tablas del sistema: guarda los
    datos diarios EN CRUDO (no features ya calculadas), exactamente el esquema de
    ``despliegue/historial_semilla.csv``. El servicio recalcula desde aquí las 17
    features del modelo (base_28, razones, precio_promedio_pct_7, internas), igual
    que el notebook; guardar el crudo permite cambiar la definición de las features
    sin recargar nada.

    Se alimenta subiendo el reporte mensual de ventas (.xlsx) por
    ``POST /api/prediccion/ingesta`` o por la pestaña "Cargar ventas mensuales" de la
    UI; ver ``services/prediccion/ingesta.py``. No hay registro de ventas una a una:
    el negocio ya tiene su sistema transaccional y no es el objetivo de este proyecto.

    Solo se sirven REGULAR, PREMIUM y GLP; BIODIESEL se eliminó de la API.
    """

    __tablename__ = "historial_ventas"
    __table_args__ = (
        UniqueConstraint("fecha", "producto", name="uq_historial_fecha_producto"),
    )

    id = Column(Integer, primary_key=True, index=True)

    fecha = Column(Date, nullable=False, index=True)
    producto = Column(String, nullable=False, index=True)

    # Datos crudos diarios necesarios para reconstruir las 17 features.
    cantidad = Column(Numeric(12, 3), nullable=False)  # galones despachados en el día
    precio_promedio = Column(Numeric(10, 2), nullable=False)  # soles/galón, sin IGV
    n_transacciones_totales = Column(Integer, nullable=False)
    proporcion_transacciones_grandes = Column(Numeric(6, 4), nullable=False)
