"""Temperatura máxima del día objetivo (feature contemporánea del modelo).

En operación la ``temperatura_max`` se toma del PRONÓSTICO de Open-Meteo
(``api.open-meteo.com/v1/forecast``, sin API key). Si el pronóstico falla o no
cubre la fecha pedida, se usa como respaldo el promedio histórico de la
temperatura máxima de ese mismo mes, dejando un warning en el log.

Un fallo de clima NUNCA debe tumbar la predicción: todas las rutas de error
devuelven un valor de respaldo en lugar de propagar la excepción.
"""

from __future__ import annotations

import logging
from datetime import date

import requests

logger = logging.getLogger(__name__)

# Ubicación del grifo (misma que en dataframe.ipynb: zona de Lambayeque, Perú).
LATITUD = -6.7714
LONGITUD = -79.8409

URL_PRONOSTICO = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 10

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


def obtener_temperatura_max(fecha: date) -> tuple[float, str]:
    """Devuelve (temperatura_max, fuente) para ``fecha``.

    ``fuente`` es ``"pronostico"`` si vino de Open-Meteo, o ``"respaldo_historico"``
    si se usó el promedio mensual. Nunca levanta excepción.
    """
    try:
        respuesta = requests.get(
            URL_PRONOSTICO,
            params={
                "latitude": LATITUD,
                "longitude": LONGITUD,
                "daily": "temperature_2m_max",
                "start_date": fecha.isoformat(),
                "end_date": fecha.isoformat(),
                "timezone": "America/Lima",
            },
            timeout=TIMEOUT_S,
        )
        respuesta.raise_for_status()
        diario = respuesta.json().get("daily", {})
        temperaturas = diario.get("temperature_2m_max") or []
        if temperaturas and temperaturas[0] is not None:
            return float(temperaturas[0]), "pronostico"
        logger.warning(
            "Open-Meteo no devolvió temperatura para %s; se usa el respaldo histórico.",
            fecha,
        )
    except (requests.RequestException, ValueError) as e:
        logger.warning(
            "Fallo al obtener el pronóstico de Open-Meteo para %s (%s); "
            "se usa el respaldo histórico.",
            fecha,
            e,
        )
    return temperatura_max_respaldo(fecha), "respaldo_historico"
