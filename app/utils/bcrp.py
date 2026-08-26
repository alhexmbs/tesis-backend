import pandas as pd
import io
import numpy as np
import os
import re
import holidays
import requests

# Nota: el BCRP usa abreviaturas de mes distintas según la frecuencia de la serie.
# Las series diarias devuelven "Set" para setiembre; las mensuales devuelven "Sep".
MESES_ES = {
    "Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Ago": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12,
}


def obtener_serie_mensual_bcrp(codigo: str, fecha_inicio: str, fecha_fin: str,
                                value_name: str = "valor") -> pd.DataFrame:
    """Descarga una serie mensual del BCRP y la devuelve como DataFrame(fecha, value_name)."""
    url = (
        f"https://estadisticas.bcrp.gob.pe/estadisticas/series/api/"
        f"{codigo}/json/{fecha_inicio}/{fecha_fin}/esp"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    respuesta = requests.get(url, headers=headers, timeout=30)
    respuesta.raise_for_status()
    data = respuesta.json()

    periodos = data.get("periods", [])
    if not periodos:
        print(f"El BCRP respondió sin datos para el código '{codigo}' en el rango {fecha_inicio} a {fecha_fin}.")
        return pd.DataFrame(columns=["fecha", value_name])

    filas = []
    for periodo in periodos:
        mes_str, anio_str = periodo["name"].split(".")
        fecha = pd.Timestamp(year=int(anio_str), month=MESES_ES[mes_str], day=1)
        valor_raw = periodo["values"][0]
        valor = None if valor_raw == "n.d." else float(valor_raw)
        filas.append({"fecha": fecha, value_name: valor})

    return pd.DataFrame(filas).sort_values("fecha").reset_index(drop=True)


def _empalmar_tramos(tramos, fecha_inicio_usuario: str, fecha_fin_usuario: str) -> pd.DataFrame:
    """
    Descarga cada tramo y los empalma (chain-linking) en una sola serie continua.
    Recorre de más reciente a más antiguo: en cada mes de frontera compartido calcula
    factor = valor_del_tramo_siguiente / valor_de_este_tramo, y reescala TODO el tramo
    actual por ese factor antes de pegarlo.
    """
    if len(tramos) == 1:
        codigo, ini, fin = tramos[0]
        return obtener_serie_mensual_bcrp(codigo, ini or fecha_inicio_usuario, fin or fecha_fin_usuario)

    segmentos = [
        obtener_serie_mensual_bcrp(codigo, ini or fecha_inicio_usuario, fin or fecha_fin_usuario)
        for codigo, ini, fin in tramos
    ]

    piezas = [segmentos[-1]]
    for i in range(len(segmentos) - 2, -1, -1):
        seg_actual = segmentos[i].copy()
        mes_corte = seg_actual["fecha"].max()

        valor_actual = seg_actual.loc[seg_actual["fecha"] == mes_corte, "valor"].iloc[0]
        valor_referencia = piezas[0].loc[piezas[0]["fecha"] == mes_corte, "valor"].iloc[0]
        factor = valor_referencia / valor_actual

        seg_actual["valor"] = seg_actual["valor"] * factor
        seg_actual = seg_actual[seg_actual["fecha"] < mes_corte]  # el mes de corte ya viene del tramo siguiente
        piezas.insert(0, seg_actual)

    return pd.concat(piezas, ignore_index=True).sort_values("fecha").reset_index(drop=True)


def _a_timestamp(periodo_str: str) -> pd.Timestamp:
    return pd.Period(periodo_str, freq="M").to_timestamp()
