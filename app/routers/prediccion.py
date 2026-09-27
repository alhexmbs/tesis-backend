from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.prediccion import (
    HistorialResponse,
    IngestaResponse,
    MetricasResponse,
    PredecirRangoRequest,
    PredecirRangoResponse,
    PredecirRequest,
    PredecirResponse,
)
from app.services.prediccion.features import HistorialInsuficiente
from app.services.prediccion.ingesta import ArchivoInvalido, ingerir_ventas_mensuales
from app.services.prediccion.servicio import (
    FechaEnPasado,
    ProductoNoServido,
    listar_historial,
    metricas_modelo,
    predecir_dia,
    predecir_rango,
)

router = APIRouter(prefix="/api/prediccion", tags=["Predicción"])


def _error_422(e: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.post("/predecir", response_model=PredecirResponse)
def predecir(request: PredecirRequest, db: Annotated[Session, Depends(get_db)]):
    """Predice los galones de un producto para una fecha. Si la fecha queda varios
    días por delante del último día del historial, esos días intermedios se estiman
    con el propio modelo y la respuesta lo informa en ``dias_estimados`` y ``notas``.
    Si el historial es insuficiente (< 28 días previos), la fecha pasa de 15 días
    desde el último día cargado o la fecha ya pasó, responde 422 en lugar de una
    predicción silenciosamente incorrecta."""
    try:
        return predecir_dia(
            db,
            producto=request.producto,
            fecha=request.fecha,
            temperatura_max=request.temperatura_max,
        )
    except (ProductoNoServido, HistorialInsuficiente, FechaEnPasado) as e:
        raise _error_422(e)


@router.post("/predecir-rango", response_model=PredecirRangoResponse)
def predecir_rango_endpoint(
    request: PredecirRangoRequest, db: Annotated[Session, Depends(get_db)]
):
    """Predicción recursiva de varios días: cada día predicho se incorpora al
    historial para el siguiente. El rango se recorta para no pasar de 15 días desde
    el último día con ventas cargadas; el recorte se informa en ``notas``. La fecha de
    inicio no puede ser anterior a hoy: hacia atrás no se pronostica, se consulta el
    historial."""
    try:
        return predecir_rango(
            db,
            producto=request.producto,
            fecha_inicio=request.fecha_inicio,
            dias=request.dias,
        )
    except (ProductoNoServido, HistorialInsuficiente, FechaEnPasado) as e:
        raise _error_422(e)


@router.post(
    "/ingesta", response_model=IngestaResponse, status_code=status.HTTP_201_CREATED
)
async def ingestar_ventas(
    archivo: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
):
    """Carga el reporte mensual de ventas (.xlsx) en el historial que alimenta al
    modelo. Agrega las transacciones a nivel día x producto y hace upsert, así que
    volver a subir un mes ya cargado lo actualiza en lugar de duplicarlo."""
    if not (archivo.filename or "").lower().endswith((".xlsx", ".xls")):
        raise _error_422(
            ValueError("Solo se aceptan reportes de ventas en formato .xlsx.")
        )
    try:
        return ingerir_ventas_mensuales(db, await archivo.read())
    except (ArchivoInvalido, ValueError) as e:
        raise _error_422(e)


@router.get("/historial/{producto}", response_model=list[HistorialResponse])
def obtener_historial(producto: str, db: Annotated[Session, Depends(get_db)]):
    """Historial de ventas reales registrado para un producto, ordenado por fecha."""
    try:
        return listar_historial(db, producto)
    except ProductoNoServido as e:
        raise _error_422(e)


@router.get("/metricas", response_model=MetricasResponse)
def obtener_metricas():
    """Métricas de holdout del modelo (de config_servicio.json), solo para
    REGULAR, PREMIUM y GLP."""
    return metricas_modelo()
