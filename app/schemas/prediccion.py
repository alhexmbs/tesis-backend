from datetime import date

from pydantic import BaseModel, ConfigDict, Field


# ==========================================
# PREDICCIÓN DE UN DÍA
# ==========================================
class PredecirRequest(BaseModel):
    producto: str
    fecha: date
    # Normalmente se deja vacío y se usa el pronóstico de Open-Meteo.
    temperatura_max: float | None = None


class PredecirResponse(BaseModel):
    producto: str
    fecha: date
    prediccion_galones: float
    # Media de la cantidad de los 28 días previos (la base_28 del modelo). Se expone
    # con nombre llano porque la UI la muestra como referencia al usuario final.
    promedio_diario_28: float
    # Último precio_promedio registrado. Informativo: el modelo no simula cambios de
    # precio, el régimen de precios entra congelado.
    precio_referencia: float
    temperatura_max: float
    fuente_temperatura: str  # "pronostico" | "respaldo_historico" | "informado"
    ultimo_dia_real: date
    # Días entre el final del historial real y la fecha pedida que se estimaron con
    # el propio modelo (0 si la fecha es el día siguiente al último dato real).
    dias_estimados: int = 0
    notas: list[str] = []
    # Trazabilidad del modelo: la UI no las muestra.
    features_usadas: dict[str, float]


# ==========================================
# PREDICCIÓN DE RANGO (recursiva)
# ==========================================
class PredecirRangoRequest(BaseModel):
    producto: str
    fecha_inicio: date
    # Tope duro: sin ventas diarias que refresquen la serie, proyectar más de 15 días
    # desde el final del historial no aporta calidad (ver MAX_HORIZONTE_DIAS).
    dias: int = Field(ge=1, le=15)


class PrediccionDia(BaseModel):
    fecha: date
    prediccion_galones: float
    temperatura_max: float
    fuente_temperatura: str


class PredecirRangoResponse(BaseModel):
    producto: str
    fecha_inicio: date
    # Días efectivamente devueltos, tras recortar al horizonte máximo.
    dias: int
    dias_solicitados: int
    precio_referencia: float
    predicciones: list[PrediccionDia]
    ultimo_dia_real: date
    dias_estimados: int = 0
    notas: list[str] = []


# ==========================================
# HISTORIAL DE VENTAS
# ==========================================
class IngestaResponse(BaseModel):
    """Resultado de cargar un reporte mensual de ventas (.xlsx)."""

    filas_guardadas: int
    # Días del arranque absoluto del historial sin ninguna venta: no hay un día previo
    # del que arrastrar el precio, así que no se pueden guardar.
    filas_omitidas: int
    fecha_inicio: date
    fecha_fin: date
    productos: list[str]
    # Días-producto que el reporte no registró y que se guardaron como cero real.
    dias_sin_ventas: int


class HistorialResponse(BaseModel):
    id: int
    fecha: date
    producto: str
    cantidad: float
    precio_promedio: float
    n_transacciones_totales: int
    proporcion_transacciones_grandes: float

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# MÉTRICAS DEL MODELO
# ==========================================
class MetricaProducto(BaseModel):
    producto: str
    acierto_pct: float
    error_medio_galones: float
    mape: float
    mae: float
    rmse: float
    mase: float
    r2: float


class MetricasResponse(BaseModel):
    modelo: str
    fecha_entrenamiento: str
    metricas: list[MetricaProducto]
