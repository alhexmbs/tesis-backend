"""Temperatura máxima del día objetivo (feature contemporánea del modelo).

En operación la ``temperatura_max`` se toma del PRONÓSTICO de Open-Meteo
(``api.open-meteo.com/v1/forecast``, sin API key). Si el pronóstico falla o no
cubre la fecha pedida, se usa como respaldo el promedio histórico de la
temperatura máxima de ese mismo mes, dejando un warning en el log.

Un fallo de clima NUNCA debe tumbar la predicción: todas las rutas de error
devuelven un valor de respaldo en lugar de propagar la excepción.

Velocidad: una predicción pide la temperatura de muchos días (los días puente sin
ventas cargadas + los del rango). Antes había una petición HTTP por día (~0.7 s
cada una, ~7 s por predicción). Ahora UNA sola petición trae los últimos
``DIAS_PASADOS`` días y los próximos ``DIAS_FUTUROS`` y se guarda en memoria
``VIGENCIA_S`` segundos; las demás consultas se responden desde esa memoria. Los
valores son los mismos que devolvía la petición día por día.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date

import requests

logger = logging.getLogger(__name__)

# Ubicación del grifo (misma que en dataframe.ipynb: zona de Lambayeque, Perú).
LATITUD = -6.7714
LONGITUD = -79.8409

URL_PRONOSTICO = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 10

# Ventana que se descarga de una vez. 16 días es el máximo de pronóstico de
# Open-Meteo y cubre MAX_HORIZONTE_DIAS (15). 31 días hacia atrás cubren los días
# puente entre el último reporte cargado y hoy.
DIAS_PASADOS = 31
DIAS_FUTUROS = 16

# Cuánto dura en memoria la descarga: el pronóstico no cambia de un minuto a otro.
VIGENCIA_S = 60 * 60
# Si Open-Meteo falla, no se reintenta en cada día del rango (cada intento podría
# esperar TIMEOUT_S): se usa el respaldo durante este tiempo y luego se reintenta.
ESPERA_TRAS_FALLO_S = 5 * 60

# Memoria compartida entre peticiones: {fecha: temperatura} + cuándo se descargó.
_cache: dict[date, float] = {}
_cache_hasta = 0.0  # momento (time.monotonic) en que la memoria deja de valer
_lock = threading.Lock()  # Gradio atiende varias peticiones a la vez

# Promedio histórico de temperatura_max por mes (°C), calculado sobre df_meteo
# (Open-Meteo archive, 2022-07 a 2026-07). Respaldo sin dependencia de red.
TEMP_MAX_PROMEDIO_MENSUAL = {
    1: 28.37,
    2: 30.77,
    3: 30.45,
    4: 28.77,
    5: 26.75,
    6: 25.74,
    7: 24.41,
    8: 23.24,
    9: 23.23,
    10: 23.47,
    11: 24.60,
    12: 26.19,
}


def temperatura_max_respaldo(fecha: date) -> float:
    """Promedio histórico del mismo mes. Nunca falla."""
    return TEMP_MAX_PROMEDIO_MENSUAL[fecha.month]


def _descargar_pronostico() -> dict[date, float]:
    """Una sola petición: temperatura máxima de toda la ventana pasada + futura."""
    respuesta = requests.get(
        URL_PRONOSTICO,
        params={
            "latitude": LATITUD,
            "longitude": LONGITUD,
            "daily": "temperature_2m_max",
            "past_days": DIAS_PASADOS,
            "forecast_days": DIAS_FUTUROS,
            "timezone": "America/Lima",
        },
        timeout=TIMEOUT_S,
    )
    respuesta.raise_for_status()
    diario = respuesta.json().get("daily", {})
    return {
        date.fromisoformat(dia): float(temp)
        for dia, temp in zip(
            diario.get("time") or [], diario.get("temperature_2m_max") or []
        )
        if temp is not None
    }


def _temperaturas() -> dict[date, float]:
    """La memoria de temperaturas; la vuelve a descargar si ya venció."""
    global _cache, _cache_hasta
    with _lock:
        if time.monotonic() < _cache_hasta:
            return _cache
        try:
            _cache = _descargar_pronostico()
            _cache_hasta = time.monotonic() + VIGENCIA_S
        except (requests.RequestException, ValueError) as e:
            logger.warning(
                "Fallo al obtener el pronóstico de Open-Meteo (%s); se usa el "
                "respaldo histórico por %s minutos.",
                e,
                ESPERA_TRAS_FALLO_S // 60,
            )
            _cache = {}
            _cache_hasta = time.monotonic() + ESPERA_TRAS_FALLO_S
        return _cache


def obtener_temperatura_max(fecha: date) -> tuple[float, str]:
    """Devuelve (temperatura_max, fuente) para ``fecha``.

    ``fuente`` es ``"pronostico"`` si vino de Open-Meteo, o ``"respaldo_historico"``
    si se usó el promedio mensual (Open-Meteo falló o la fecha queda fuera de la
    ventana descargada). Nunca levanta excepción.
    """
    temperatura = _temperaturas().get(fecha)
    if temperatura is not None:
        return temperatura, "pronostico"
    logger.warning(
        "Open-Meteo no tiene temperatura para %s; se usa el respaldo histórico.",
        fecha,
    )
    return temperatura_max_respaldo(fecha), "respaldo_historico"
