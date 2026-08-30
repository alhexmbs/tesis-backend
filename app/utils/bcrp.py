import pandas as pd
import requests

# Nota: el BCRP usa abreviaturas de mes distintas según la frecuencia de la serie.
# Las series diarias devuelven "Set" para setiembre; las mensuales devuelven "Sep".
MESES_ES = {
    "Ene": 1, "Feb": 2, "Mar": 3, "Abr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Ago": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dic": 12,
}


class ErrorBcrp(RuntimeError):
    """El servicio del BCRP no respondió correctamente (caído, en mantenimiento o bloqueando la petición)."""


def _pedir_json_bcrp(url: str, headers: dict) -> dict:
    """Pide una URL de la API del BCRP y devuelve el JSON, con errores legibles.

    El sitio del BCRP a veces está caído o devuelve una página HTML (mantenimiento,
    bloqueo anti-bot tipo Incapsula) con status 200, lo que hace que .json() reviente
    con un "Expecting value: line 1 column 1 (char 0)" que no dice nada al usuario.
    """
    try:
        respuesta = requests.get(url, headers=headers, timeout=30)
    except requests.exceptions.RequestException as e:
        raise ErrorBcrp(f"No se pudo conectar con el BCRP ({url}): {e}") from e

    try:
        respuesta.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise ErrorBcrp(f"El BCRP respondió con error HTTP para {url}: {e}") from e

    try:
        return respuesta.json()
    except ValueError as e:
        raise ErrorBcrp(
            f"El BCRP no devolvió datos válidos para {url} "
            f"(status {respuesta.status_code}, Content-Type: {respuesta.headers.get('Content-Type')}). "
            "El sitio puede estar caído, en mantenimiento o bloqueando la petición. "
            "Verifica manualmente en https://estadisticas.bcrp.gob.pe."
        ) from e


def obtener_serie_mensual_bcrp(codigo: str, fecha_inicio: str, fecha_fin: str,
                                value_name: str = "valor") -> pd.DataFrame:
    """Descarga una serie mensual del BCRP y la devuelve como DataFrame(fecha, value_name)."""
    url = (
        f"https://estadisticas.bcrp.gob.pe/estadisticas/series/api/"
        f"{codigo}/json/{fecha_inicio}/{fecha_fin}/esp"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    data = _pedir_json_bcrp(url, headers)

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
    # Descartar tramos que no se solapan con el rango solicitado: si el rango del
    # usuario cae íntegramente después (o antes) del tramo, pedirlo igual generaría
    # un rango inválido (ini > fin) y la API devolvería una serie vacía.
    inicio_usuario = _a_timestamp(fecha_inicio_usuario)
    fin_usuario = _a_timestamp(fecha_fin_usuario)
    tramos = [
        (codigo, ini, fin) for codigo, ini, fin in tramos
        if (fin is None or _a_timestamp(fin) >= inicio_usuario)
        and (ini is None or _a_timestamp(ini) <= fin_usuario)
    ]

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
