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
from app.ui.calendario import calendario
from app.ui.componentes import (
    ENCABEZADO_HTML,
    SPINNER_HTML,
    banner,
    error_html,
    fecha_larga,
    leer_js,
    notas_html,
)
from app.utils.validaciones import ErrorValidacion, validar_fecha

PRODUCTOS = ["REGULAR", "PREMIUM", "GLP"]

ENCABEZADO_JS_ON_LOAD = leer_js("encabezado.js")

# Botón "Cargar ventas" dentro de un gr.HTML (aviso o error). Un clic en él dispara
# el evento propio `ir_carga`, que en Python cambia a la pestaña de carga. Gradio
# solo crea `.ir_carga(...)` si el nombre aparece entre comillas en este JS.
IR_CARGA_JS = (
    "element.addEventListener('click', (e) => {"
    " if (e.target.closest('.boton-ir-carga')) trigger('ir_carga'); });"
)
BOTON_IR_CARGA = (
    '<button type="button" class="boton-ir-carga">'
    '<i class="bi bi-upload"></i> Cargar ventas</button>'
)


def _ultimo_dia(producto: str) -> date | None:
    """Último día con ventas cargadas del producto (None si no hay o falla la BD)."""
    try:
        db = SessionLocal()
        try:
            return ultimo_dia_historial(db, producto)
        finally:
            db.close()
    except Exception:
        return None


def _aviso_sin_ventas(producto: str, ultimo: date | None, titulo: str) -> str:
    """Aviso en lenguaje llano + botón que lleva a la pestaña de carga."""
    if ultimo is None:
        detalle = f"Todavía no hay ventas cargadas de {producto}."
    else:
        detalle = f"El último registro de {producto} es del {fecha_larga(ultimo)}."
    cuerpo = (
        f'<div class="msg-cuerpo">{detalle} Carga el reporte más reciente para '
        f"poder predecir.</div>{BOTON_IR_CARGA}"
    )
    return banner("info", "exclamation-circle", titulo, cuerpo)


def limites_fecha(producto: str):
    """Rango elegible del calendario para un producto.

    - mínimo: hoy (hacia atrás no se pronostica).
    - máximo: último día con ventas + MAX_HORIZONTE_DIAS (más lejos el modelo no
      proyecta).
    - fecha propuesta: el día siguiente al último con ventas, o hoy si ese día ya
      pasó.

    Si el máximo quedó antes de hoy, el rango está vacío: se muestra el aviso de
    ventas desactualizadas y el calendario queda con todos los días bloqueados.

    Devuelve las actualizaciones de (calendario, aviso, botón Predecir).
    """
    hoy = date.today()
    ultimo = _ultimo_dia(producto)
    maximo = ultimo + timedelta(days=MAX_HORIZONTE_DIAS) if ultimo else None

    if maximo is None or maximo < hoy:
        aviso = _aviso_sin_ventas(producto, ultimo, "Las ventas están desactualizadas")
        # mínimo > máximo: Flatpickr deshabilita todos los días.
        ayer = hoy - timedelta(days=1)
        return (
            gr.update(value=None, minimo=hoy.isoformat(), maximo=ayer.isoformat()),
            gr.update(value=aviso),
            gr.update(interactive=False),
        )

    sugerida = max(ultimo + timedelta(days=1), hoy)
    return (
        gr.update(
            value=sugerida.isoformat(),
            minimo=hoy.isoformat(),
            maximo=maximo.isoformat(),
        ),
        gr.update(value=""),
        gr.update(interactive=True),
    )


def ir_a_carga():
    return gr.Tabs(selected="carga")


def bloquear_boton(texto: str):
    """Mientras predice: botón deshabilitado, así no se envían clics repetidos."""
    return gr.update(value=texto, interactive=False)


def _ejecutar(fn, producto: str, fecha_str: str, *args):
    """Valida la fecha (AAAA-MM-DD estricto), abre la sesión y corre `fn`.

    Devuelve `(resultado, None)` o `(None, html_error)`: los dos predictores
    comparten los mismos errores esperables y el mismo manejo de la sesión. El
    calendario ya impide elegir fechas inválidas; esto es la red de seguridad.
    """
    try:
        fecha = validar_fecha(fecha_str)
    except ErrorValidacion:
        return None, error_html("Elige una fecha en el calendario")

    db = SessionLocal()
    try:
        return fn(db, producto, fecha, *args), None
    except HistorialInsuficiente:
        # El mensaje del servicio es técnico (lo usa la API): aquí va en llano.
        return None, _aviso_sin_ventas(
            producto,
            _ultimo_dia(producto),
            "No hay ventas recientes para predecir esta fecha",
        )
    except (ProductoNoServido, FechaEnPasado) as e:
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
        f"<li><b>Ventas cargadas hasta:</b> {fecha_larga(r['ultimo_dia_real'])}</li>"
    )


# --------------------------------------------------------------------------- #
# Predicción diaria
# --------------------------------------------------------------------------- #
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

    titulo = f"{r['producto']} — {fecha_larga(r['fecha'])}"
    return banner("ok", "graph-up", titulo, cuerpo)


# --------------------------------------------------------------------------- #
# Predicción de rango
# --------------------------------------------------------------------------- #
def ajustar_rango(producto: str, fecha_inicio: str | None, dias: int):
    """Al cambiar la fecha de inicio: activa "Predecir rango" y acota el slider.

    El slider no deja pedir días más allá del máximo del calendario (último día
    con ventas + MAX_HORIZONTE_DIAS).
    """
    ultimo = _ultimo_dia(producto)
    if not fecha_inicio or ultimo is None:
        return gr.update(interactive=False), gr.update()
    maximo = ultimo + timedelta(days=MAX_HORIZONTE_DIAS)
    dias_max = max((maximo - date.fromisoformat(fecha_inicio)).days + 1, 1)
    return (
        gr.update(interactive=True),
        gr.update(maximum=dias_max, value=min(int(dias), dias_max)),
    )


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
        "calendar-range",
        f"{r['producto']} — {r['dias']} días desde el {fecha_larga(r['fecha_inicio'])}",
        cuerpo,
    )

    # El gráfico necesita la fecha ISO para ordenar el eje; la tabla la muestra larga.
    detalle = tabla.assign(fecha=tabla["fecha"].map(fecha_larga))
    return tabla, resumen, detalle


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
        tipo, icono = "err", "exclamation-triangle"
        titulo = "No se pudo cargar ningún archivo"
    elif con_error:
        tipo, icono = "info", "exclamation-circle"
        titulo = f"{total} días-producto guardados · {con_error} archivo(s) con error"
    else:
        tipo, icono = "ok", "check-circle"
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
    titulo = "¿Qué tan bien predice el modelo?"
    return banner("info", "bar-chart", titulo, cuerpo), tabla


with gr.Blocks(title="Inicio") as demo:
    gr.HTML(ENCABEZADO_HTML, js_on_load=ENCABEZADO_JS_ON_LOAD)

    with gr.Tabs() as pestanas:
        # ---------------- Predicción diaria ----------------
        with gr.Tab("Predicción diaria", id="diaria"):
            p_aviso = gr.HTML(js_on_load=IR_CARGA_JS)
            gr.Markdown(
                "Elige un producto y una fecha para estimar los galones que se "
                "venderán."
            )
            gr.Markdown(
                f"Se puede elegir desde hoy hasta {MAX_HORIZONTE_DIAS} días después "
                "del último día con ventas cargadas. La fecha propuesta es el día "
                "siguiente a ese registro.",
                elem_classes="ayuda",
            )
            with gr.Row(equal_height=True):
                p_producto = gr.Dropdown(PRODUCTOS, value="REGULAR", label="Producto")
                p_fecha = calendario("Fecha")
            p_boton = gr.Button(
                "Predecir", variant="primary", size="lg", interactive=False
            )
            p_resultado = gr.HTML(js_on_load=IR_CARGA_JS)

            p_producto.change(
                limites_fecha, inputs=p_producto, outputs=[p_fecha, p_aviso, p_boton]
            )
            # Sin fecha elegida no se puede predecir.
            p_fecha.change(
                lambda f: gr.update(interactive=bool(f)),
                inputs=p_fecha,
                outputs=p_boton,
                show_progress="hidden",
            )
            (
                p_boton.click(
                    lambda: bloquear_boton("Prediciendo…"),
                    outputs=p_boton,
                    show_progress="hidden",
                )
                .then(
                    predecir_ui,
                    inputs=[p_producto, p_fecha],
                    outputs=p_resultado,
                    show_progress="full",
                )
                .then(
                    lambda: gr.update(value="Predecir", interactive=True),
                    outputs=p_boton,
                    show_progress="hidden",
                )
            )

        # ---------------- Predicción de rango ----------------
        with gr.Tab("Predicción de rango", id="rango"):
            r_aviso = gr.HTML(js_on_load=IR_CARGA_JS)
            gr.Markdown(
                "Elige un producto, una fecha de inicio y cuántos días quieres "
                "estimar."
            )
            gr.Markdown(
                "Como el reporte de ventas llega una vez al mes, la proyección "
                f"alcanza hasta {MAX_HORIZONTE_DIAS} días después del último día "
                "con ventas cargadas.",
                elem_classes="ayuda",
            )
            with gr.Row(equal_height=True):
                r_producto = gr.Dropdown(PRODUCTOS, value="REGULAR", label="Producto")
                r_fecha = calendario("Fecha de inicio")
                r_dias = gr.Slider(
                    1, MAX_HORIZONTE_DIAS, value=7, step=1, label="Días a predecir"
                )
            r_boton = gr.Button(
                "Predecir rango", variant="primary", size="lg", interactive=False
            )
            r_resumen = gr.HTML(js_on_load=IR_CARGA_JS)
            r_grafico = gr.LinePlot(
                x="fecha", y="galones", label="Predicción (galones/día)"
            )
            r_tabla = gr.Dataframe(label="Detalle")

            r_producto.change(
                limites_fecha, inputs=r_producto, outputs=[r_fecha, r_aviso, r_boton]
            )
            r_fecha.change(
                ajustar_rango,
                inputs=[r_producto, r_fecha, r_dias],
                outputs=[r_boton, r_dias],
                show_progress="hidden",
            )
            (
                r_boton.click(
                    lambda: bloquear_boton("Prediciendo…"),
                    outputs=r_boton,
                    show_progress="hidden",
                )
                .then(
                    predecir_rango_ui,
                    inputs=[r_producto, r_fecha, r_dias],
                    outputs=[r_grafico, r_resumen, r_tabla],
                    show_progress="full",
                )
                .then(
                    lambda: gr.update(value="Predecir rango", interactive=True),
                    outputs=r_boton,
                    show_progress="hidden",
                )
            )

        # ---------------- Carga del reporte mensual ----------------
        with gr.Tab("Cargar ventas mensuales", id="carga"):
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
            v_xlsx_boton = gr.Button(
                "Cargar al historial", variant="primary", size="lg"
            )
            v_spinner = gr.HTML(SPINNER_HTML, visible=False)
            v_xlsx_resultado = gr.HTML()

            # Pasos encadenados: bloquear el panel y encender el spinner → ingesta →
            # vaciar el selector y reactivar → recalcular los calendarios (con ventas
            # nuevas cambia el máximo). Los últimos pasos no escriben en
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
                .then(
                    limites_fecha,
                    inputs=p_producto,
                    outputs=[p_fecha, p_aviso, p_boton],
                    show_progress="hidden",
                )
                .then(
                    limites_fecha,
                    inputs=r_producto,
                    outputs=[r_fecha, r_aviso, r_boton],
                    show_progress="hidden",
                )
            )

        # ---------------- Métricas ----------------
        with gr.Tab("Métricas del modelo", id="metricas"):
            m_texto = gr.HTML()
            m_tabla = gr.Dataframe(label="Detalle por producto")
            m_boton = gr.Button("Actualizar métricas")
            m_boton.click(cargar_metricas_ui, outputs=[m_texto, m_tabla])

    # Al abrir la página: métricas y límites de los dos calendarios (calculados en
    # cada visita, no al arrancar el servidor, para que "hoy" sea siempre hoy).
    demo.load(cargar_metricas_ui, outputs=[m_texto, m_tabla])
    demo.load(limites_fecha, inputs=p_producto, outputs=[p_fecha, p_aviso, p_boton])
    demo.load(limites_fecha, inputs=r_producto, outputs=[r_fecha, r_aviso, r_boton])

    # Botón "Cargar ventas" de los avisos y errores → pestaña de carga, sin salir de
    # la página.
    for html in (p_aviso, p_resultado, r_aviso, r_resumen):
        html.ir_carga(ir_a_carga, outputs=pestanas)
