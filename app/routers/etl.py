from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.services.etl.carga import (
    guardar_datos_meteorologicos,
    guardar_indice_precio_combustibles,
    guardar_precio_wti,
    guardar_tipo_cambio,
    guardar_ventas_historicas,
    obtener_historico_para_lags,
)
from app.services.etl.extraction import (
    extraer_excel,
    extraer_txt,
    obtener_data_bcrp_cambio_dolar,
    obtener_data_bcrp_indices,
    obtener_data_eia,
    obtener_data_meteorologica,
)
from app.services.etl.pipeline import construir_dataset_modelo
from app.services.etl.transformation import feature_engineering, limpiar_datos

router = APIRouter(prefix="/api/etl", tags=["ETL"])

# Código de serie del BCRP para el tipo de cambio interbancario venta (serie diaria).
CODIGO_BCRP_TIPO_CAMBIO = "PD04638PD"


@router.post("/ejecutar")
async def ejecutar_etl(
    archivo: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
):
    """Corre el pipeline completo: extrae las ventas del archivo subido y las 4 fuentes
    externas para ese mismo rango de fechas, guarda cada fuente cruda en su tabla de
    staging, arma el dataset final para el modelo y lo guarda en ventas_historicas."""
    try:
        contenido = await archivo.read()
        if archivo.filename and archivo.filename.lower().endswith((".xlsx", ".xls")):
            df_ventas_crudo = extraer_excel(contenido)
        else:
            df_ventas_crudo = extraer_txt(contenido)

        # Limpiar y agrupar las ventas propias a nivel diario
        df_diario = limpiar_datos(df_ventas_crudo)

        # El rango de fechas de las 4 fuentes externas se deriva del propio archivo de
        # ventas, para que siempre correspondan exactamente al periodo que se procesa.
        fecha_min = df_diario["fecha"].min()
        fecha_max = df_diario["fecha"].max()
        fecha_inicio = fecha_min.strftime("%Y-%m-%d")
        fecha_fin = fecha_max.strftime("%Y-%m-%d")

        # La EIA no publica precio del WTI los fines de semana/feriados de EE.UU.; se
        # pide con 5 días de margen hacia atrás para que el ffill() posterior (en
        # construir_dataset_modelo) tenga un valor previo del cual arrastrar en el
        # primer día real de venta.
        fecha_inicio_wti = (fecha_min - timedelta(days=5)).strftime("%Y-%m-%d")

        # El índice de precio de combustibles del BCRP es mensual y su API usa el
        # formato "año-mes" sin cero a la izquierda (mismo formato que MIGRACIONES_BCRP
        # en extraction.py, ej. "2023-3").
        fecha_inicio_mensual = f"{fecha_min.year}-{fecha_min.month}"
        fecha_fin_mensual = f"{fecha_max.year}-{fecha_max.month}"

        # Traer las 4 fuentes externas
        df_wti = obtener_data_eia(fecha_inicio_wti, fecha_fin, settings.eia_api_key)
        df_tipo_cambio = obtener_data_bcrp_cambio_dolar(CODIGO_BCRP_TIPO_CAMBIO, fecha_inicio, fecha_fin)
        df_clima = obtener_data_meteorologica(fecha_inicio, fecha_fin)
        df_indices = obtener_data_bcrp_indices(fecha_inicio_mensual, fecha_fin_mensual)

        # Guardar cada fuente externa cruda en su tabla de staging (trazabilidad)
        guardar_precio_wti(db, df_wti)
        guardar_tipo_cambio(db, df_tipo_cambio)
        guardar_datos_meteorologicos(db, df_clima)
        guardar_indice_precio_combustibles(db, df_indices)

        # Traer el historial reciente ya guardado (fin del mes anterior) para que los
        # primeros días del lote nuevo no se queden sin lags/promedios móviles
        productos = df_diario["producto"].unique().tolist()
        historico_dicts = obtener_historico_para_lags(db, fecha_min.date(), productos)

        # Calcular rezagos y promedios móviles sobre las ventas propias
        df_features = feature_engineering(df_diario, historico_dicts)

        # construir_dataset_modelo espera la columna "tipo_cambio_venta", mientras que
        # la extracción cruda del BCRP devuelve "valor" (la misma que se guardó arriba).
        df_tipo_cambio_modelo = df_tipo_cambio.rename(columns={"valor": "tipo_cambio_venta"})

        # Unir ventas + las 4 fuentes externas en el dataset final para el modelo
        df_final = construir_dataset_modelo(df_features, df_wti, df_indices, df_tipo_cambio_modelo, df_clima)

        # Recortar de vuelta al rango exacto de las ventas del archivo subido: descarta
        # tanto el margen de 5 días usado para el WTI como los días de historial
        # (fin del mes anterior) que feature_engineering concatenó solo para poder
        # calcular los lags/promedios de los primeros días del lote nuevo.
        df_final = df_final[(df_final["fecha"] >= fecha_min) & (df_final["fecha"] <= fecha_max)]

        guardar_ventas_historicas(db, df_final)

        return {
            "filas_procesadas": len(df_final),
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
