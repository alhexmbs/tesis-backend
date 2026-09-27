from datetime import date, timedelta

import gradio as gr
import pandas as pd

from app.database import SessionLocal
from app.services.prediccion.features import HistorialInsuficiente
from app.services.prediccion.ingesta import ArchivoInvalido, ingerir_ventas_mensuales
from app.services.prediccion.servicio import (
    MAX_HORIZONTE_DIAS,
    FechaEnPasado,
    ProductoNoServido,
    metricas_modelo,
    predecir_dia,
    predecir_rango,
    ultimo_dia_historial,
)
from app.ui.componentes import (
    CERRAR_SESION_HTML,
    RELOJ_HTML,
    SPINNER_HTML,
    banner,
    error_html,
    leer_js,
    notas_html,
)
from app.utils.validaciones import ErrorValidacion, validar_fecha

PRODUCTOS = ["REGULAR", "PREMIUM", "GLP"]

RELOJ_JS_ON_LOAD = leer_js("reloj.js")
CERRAR_SESION_JS_ON_LOAD = leer_js("cerrar_sesion.js")

# Filtro de tecleo del navegador: en los campos de fecha solo entran dígitos y
# guiones, con el largo justo de AAAA-MM-DD. El formato lo verifica `validar_fecha`
# en el servidor; esto solo evita que el usuario llegue a escribir letras.
SOLO_FECHA_JS = "(v) => (v || '').replace(/[^0-9-]/g, '').slice(0, 10)"


def _ejecutar(fn, producto: str, fecha_str: str, *args):
    """Valida la fecha (AAAA-MM-DD estricto), abre la sesión y corre `fn`.

    Devuelve `(resultado, None)` o `(None, html_error)`: los dos predictores
    comparten los mismos errores esperables y el mismo manejo de la sesión.
    """
    try:
        fecha = validar_fecha(fecha_str)
    except ErrorValidacion as e:
        return None, error_html("Fecha inválida", str(e))

    db = SessionLocal()
    try:
        return fn(db, producto, fecha, *args), None
    except (ProductoNoServido, HistorialInsuficiente, FechaEnPasado) as e:
        return None, error_html("No se pudo predecir", str(e))
    except Exception as e:
        return None, error_html("Error inesperado", str(e))
    finally:
        db.close()


def _items_contexto(r: dict) -> str:
    """Filas comunes a los dos resúmenes: precio usado y hasta cuándo hay ventas."""
    return (
        f"<li><b>Precio considerado:</b> S/ {r['precio_referencia']:.2f} "
        "(el último registrado)</li>"
        f"<li><b>Ventas cargadas hasta:</b> {r['ultimo_dia_real']}</li>"
    )


# --------------------------------------------------------------------------- #
# Predicción diaria
# --------------------------------------------------------------------------- #
def fecha_sugerida(producto: str) -> str:
    """Día siguiente al final del historial, nunca anterior a hoy.

    El historial se alimenta con el reporte mensual, así que casi siempre va por
    detrás del calendario: el día siguiente al último dato cargado suele ser una
    fecha ya pasada, y hacia atrás no se pronostica. Por eso se propone el más
    reciente de los dos (último + 1 u hoy). Si el historial quedó muy atrás, el
    servicio responderá pidiendo cargar el reporte más reciente.
    """
    try:
        db = SessionLocal()
        try:
            ultimo = ultimo_dia_historial(db, producto)
        finally:
            db.close()
    except Exception:
        ultimo = None
    hoy = date.today()
    siguiente = (ultimo + timedelta(days=1)) if ultimo is not None else hoy
    return max(siguiente, hoy).isoformat()


def predecir_ui(producto: str, fecha_str: str):
    r, error = _ejecutar(predecir_dia, producto, fecha_str)
    if error:
        return error

    # Solo lo que el encargado del grifo puede leer y usar: galones del día, con qué
    # se está comparando y hasta cuándo llegan las ventas cargadas. Las 17 features
    # (lags, razones, cv) siguen en la respuesta de la API, pero no se muestran.
    cuerpo = (
        f'<div class="cifra">{r["prediccion_galones"]:,.0f}'
        '<span class="unidad">galones</span></div>'
        '<ul class="msg-detalle">'
        "<li><b>Venta diaria promedio del último mes:</b> "
        f"{r['promedio_diario_28']:,.0f} galones</li>"
        f"<li><b>Temperatura máxima esperada:</b> {r['temperatura_max']:.0f} °C</li>"
        f"{_items_contexto(r)}"
        "</ul>"
    ) + notas_html(r["notas"])

    return banner("ok", "🔮", f"{r['producto']} — {r['fecha']}", cuerpo)


# --------------------------------------------------------------------------- #
# Predicción de rango
# --------------------------------------------------------------------------- #
def predecir_rango_ui(producto: str, fecha_inicio_str: str, dias: int):
    r, error = _ejecutar(predecir_rango, producto, fecha_inicio_str, int(dias))
    if error:
        return None, error, None

    tabla = pd.DataFrame(r["predicciones"])[["fecha", "prediccion_galones"]]
    tabla["fecha"] = tabla["fecha"].astype(str)
    tabla = tabla.rename(columns={"prediccion_galones": "galones"})
    total = float(tabla["galones"].sum())

    cuerpo = (
        f'<div class="cifra">{total:,.0f}'
        '<span class="unidad">galones en total</span></div>'
        '<ul class="msg-detalle">'
        f"<li><b>Promedio por día:</b> {total / len(tabla):,.0f} galones</li>"
        f"{_items_contexto(r)}"
        "</ul>"
    ) + notas_html(r["notas"])

    resumen = banner(
        "ok",
        "📈",
        f"{r['producto']} — {r['dias']} días desde {r['fecha_inicio']}",
        cuerpo,
    )

    return tabla, resumen, tabla


# --------------------------------------------------------------------------- #
# Carga del reporte mensual de ventas
# --------------------------------------------------------------------------- #
def inicio_carga_xlsx():
    """Bloquea el panel y muestra el spinner mientras corre la ingesta."""
    return (
        gr.update(value="⏳ Procesando…", interactive=False),  # botón
        gr.update(interactive=False),  # selector de archivos
        gr.update(visible=True),  # spinner
        gr.update(value=""),  # limpia el resultado de la carga anterior
    )


def fin_carga_xlsx():
    """Devuelve el panel a su estado inicial.

    NO toca el componente del resultado: el mensaje de la carga tiene que seguir a
    la vista después de vaciar el selector de archivos.
    """
    return (
        gr.update(value="Cargar al historial", interactive=True),  # botón
        gr.update(value=None, interactive=True),  # selector vacío otra vez
        gr.update(visible=False),  # spinner
    )


def cargar_xlsx_ui(archivos, progress=gr.Progress()):
    """Carga uno o varios reportes mensuales .xlsx en el historial del modelo."""
    if not archivos:
        return error_html(
            "No hay archivos seleccionados",
            "Elige al menos un archivo .xlsx del reporte de ventas.",
        )

    if not isinstance(archivos, list):
        archivos = [archivos]

    db = SessionLocal()
    lineas = []
    total = 0
    con_error = 0
    try:
        # Ordenados por nombre para que los meses entren en orden cronológico: el
        # arrastre de precio de los días sin ventas depende del mes anterior.
        for ruta in progress.tqdm(sorted(archivos, key=str), desc="Procesando"):
            nombre = str(ruta).replace("\\", "/").split("/")[-1]
            try:
                with open(ruta, "rb") as f:
                    r = ingerir_ventas_mensuales(db, f.read())
            except (ArchivoInvalido, ValueError) as e:
                con_error += 1
                lineas.append(
                    f'<li><span class="ico-err">✕</span> <b>{nombre}</b>: {e}</li>'
                )
                continue
            except Exception as e:  # noqa: BLE001 - se reporta por archivo
                con_error += 1
                lineas.append(
                    f'<li><span class="ico-err">✕</span> <b>{nombre}</b>: '
                    f"error inesperado: {e}</li>"
                )
                continue

            total += r["filas_guardadas"]
            detalle = (
                f'<li><span class="ico-ok">✓</span> <b>{nombre}</b>: '
                f"{r['filas_guardadas']} días-producto "
                f"({r['fecha_inicio']} a {r['fecha_fin']}, "
                f"{', '.join(r['productos'])})"
            )
            if r["dias_sin_ventas"]:
                detalle += (
                    f" · {r['dias_sin_ventas']} día(s) sin ventas guardados como 0"
                )
            if r["filas_omitidas"]:
                detalle += (
                    f" · {r['filas_omitidas']} omitido(s) por falta de precio previo"
                )
            lineas.append(detalle + "</li>")
    finally:
        db.close()

    correctos = len(lineas) - con_error
    if con_error and not correctos:
        tipo, icono = "err", "⚠️"
        titulo = "No se pudo cargar ningún archivo"
    elif con_error:
        tipo, icono = "info", "⚠️"
        titulo = f"{total} días-producto guardados · {con_error} archivo(s) con error"
    else:
        tipo, icono = "ok", "✅"
        titulo = f"Carga completada — {total} días-producto guardados en el historial"

    cuerpo = f'<ul class="msg-archivos">{"".join(lineas)}</ul>'
    return banner(tipo, icono, titulo, cuerpo)


# --------------------------------------------------------------------------- #
# Métricas del modelo (lenguaje llano)
# --------------------------------------------------------------------------- #
def cargar_metricas_ui():
    m = metricas_modelo()
    filas = "".join(
        f"<li><b>{fila['producto']}</b> — {fila['acierto_pct']:.1f} % de acierto, "
        f"{fila['error_medio_galones']:.0f} gal/día de error medio</li>"
        for fila in m["metricas"]
    )
    cuerpo = (
        '<div class="msg-cuerpo">Evaluado sobre los <b>últimos 90 días que el '
        f"modelo nunca vio</b> (entrenado hasta {m['fecha_entrenamiento']}). "
        "Por cada producto:</div>"
        f'<ul class="msg-detalle">{filas}</ul>'
        '<div class="msg-pie"><b>Acierto</b>: qué tan cerca quedó, en promedio '
        "(100 % sería perfecto). · <b>Error medio</b>: cuántos galones, en "
        "promedio, se equivocó por día.</div>"
    )
    tabla = pd.DataFrame(m["metricas"])[
        ["producto", "acierto_pct", "error_medio_galones", "mape", "mae"]
    ]
    return banner("info", "📊", "¿Qué tan bien predice el modelo?", cuerpo), tabla


_FECHA_INICIAL = fecha_sugerida("REGULAR")


with gr.Blocks(title="Inicio") as demo:
    gr.Markdown("# BENZIN AI — Predicción de demanda de combustible")
    gr.HTML(RELOJ_HTML, js_on_load=RELOJ_JS_ON_LOAD)

    with gr.Tabs():
        # ---------------- Predicción diaria ----------------
        with gr.Tab("Predicción diaria"):
            gr.Markdown(
                "Estima cuántos galones se venderán en un día. Solo se predice de "
                "**hoy en adelante**; la **fecha** viene precargada con el día "
                "siguiente al último con ventas cargadas (o con hoy, si ese día "
                "ya pasó)."
            )
            with gr.Row():
                p_producto = gr.Dropdown(PRODUCTOS, value="REGULAR", label="Producto")
                p_fecha = gr.Textbox(
                    value=_FECHA_INICIAL, label="Fecha (AAAA-MM-DD)", max_length=10
                )
            p_boton = gr.Button("Predecir", variant="primary")
            p_resultado = gr.HTML()

            p_fecha.input(fn=None, inputs=p_fecha, outputs=p_fecha, js=SOLO_FECHA_JS)
            p_producto.change(fecha_sugerida, inputs=p_producto, outputs=p_fecha)
            p_boton.click(
                predecir_ui,
                inputs=[p_producto, p_fecha],
                outputs=p_resultado,
                show_progress="full",
            )

        # ---------------- Predicción de rango ----------------
        with gr.Tab("Predicción de rango"):
            gr.Markdown(
                "Estima varios días seguidos, de **hoy en adelante**. Como el reporte "
                "de ventas llega una vez al mes, la proyección alcanza hasta "
                f"**{MAX_HORIZONTE_DIAS} días** desde el último día con ventas "
                "cargadas; si pides más, se recorta hasta ese límite."
            )
            with gr.Row():
                r_producto = gr.Dropdown(PRODUCTOS, value="REGULAR", label="Producto")
                r_fecha = gr.Textbox(
                    value=_FECHA_INICIAL,
                    label="Fecha inicio (AAAA-MM-DD)",
                    max_length=10,
                )
                r_dias = gr.Slider(
                    1, MAX_HORIZONTE_DIAS, value=7, step=1, label="Días a predecir"
                )
            r_boton = gr.Button("Predecir rango", variant="primary")
            r_aviso = gr.HTML()
            r_grafico = gr.LinePlot(
                x="fecha", y="galones", label="Predicción (galones/día)"
            )
            r_tabla = gr.Dataframe(label="Detalle")

            r_fecha.input(fn=None, inputs=r_fecha, outputs=r_fecha, js=SOLO_FECHA_JS)
            r_producto.change(fecha_sugerida, inputs=r_producto, outputs=r_fecha)
            r_boton.click(
                predecir_rango_ui,
                inputs=[r_producto, r_fecha, r_dias],
                outputs=[r_grafico, r_aviso, r_tabla],
                show_progress="full",
            )

        # ---------------- Carga del reporte mensual ----------------
        with gr.Tab("Cargar ventas mensuales"):
            gr.Markdown(
                "Sube el **reporte mensual de ventas** (`.xlsx`) que exporta el sistema "
                "del grifo. Se agregan las transacciones a nivel día × producto y se "
                "guardan en el historial que alimenta al modelo.\n\n"
                "Puedes subir varios meses a la vez. La carga es **idempotente**: "
                "volver a subir un mes ya cargado lo actualiza, no lo duplica."
            )
            v_xlsx = gr.File(
                label="Reportes de ventas (.xlsx)",
                file_types=[".xlsx", ".xls"],
                file_count="multiple",
                type="filepath",
            )
            v_xlsx_boton = gr.Button("Cargar al historial", variant="primary")
            v_spinner = gr.HTML(SPINNER_HTML, visible=False)
            v_xlsx_resultado = gr.HTML()

            # Tres pasos encadenados: bloquear el panel y encender el spinner →
            # ingesta → vaciar el selector y reactivar. El último paso no escribe en
            # v_xlsx_resultado, así el mensaje sobrevive al refresco del panel.
            (
                v_xlsx_boton.click(
                    inicio_carga_xlsx,
                    outputs=[v_xlsx_boton, v_xlsx, v_spinner, v_xlsx_resultado],
                    show_progress="hidden",
                )
                .then(
                    cargar_xlsx_ui,
                    inputs=v_xlsx,
                    outputs=v_xlsx_resultado,
                    show_progress="hidden",
                )
                .then(
                    fin_carga_xlsx,
                    outputs=[v_xlsx_boton, v_xlsx, v_spinner],
                    show_progress="hidden",
                )
            )

        # ---------------- Métricas ----------------
        with gr.Tab("Métricas del modelo"):
            m_texto = gr.HTML()
            m_tabla = gr.Dataframe(label="Detalle por producto")
            m_boton = gr.Button("Actualizar métricas")
            m_boton.click(cargar_metricas_ui, outputs=[m_texto, m_tabla])
            demo.load(cargar_metricas_ui, outputs=[m_texto, m_tabla])

    gr.HTML(CERRAR_SESION_HTML, js_on_load=CERRAR_SESION_JS_ON_LOAD)
