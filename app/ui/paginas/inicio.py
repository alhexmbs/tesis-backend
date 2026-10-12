from datetime import date, timedelta

import gradio as gr
import pandas as pd

from app.database import SessionLocal
from app.services.entregas import PlanImposible, planificar_entregas
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
    venta_promedio_diaria,
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
        "por galón</li>"
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
    # La temperatura tampoco: el modelo sí la usa, pero al encargado no le sirve para
    # decidir nada (y genera la pregunta "¿qué tiene que ver el clima?").
    cuerpo = (
        f'<div class="cifra">{r["prediccion_galones"]:,.0f}'
        '<span class="unidad">galones</span></div>'
        '<ul class="msg-detalle">'
        "<li><b>Venta diaria promedio del último mes:</b> "
        f"{r['promedio_diario_28']:,.0f} galones</li>"
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


def _error_tipico_pct(producto: str) -> float:
    """Error típico del modelo para el producto, en % de la venta (MAPE de holdout)."""
    for fila in metricas_modelo()["metricas"]:
        if fila["producto"] == producto:
            return fila["mape"]
    return 0.0


def _pedido_html(total: float, stock: float, producto: str) -> str:
    """Bloque "cuánto pedir": lo que se venderá menos lo que ya hay en el tanque.

    - Pedido sugerido = venta estimada − stock (nunca negativo).
    - Con colchón = venta estimada + su error típico (%) − stock: por si se vende
      más de lo previsto. El % es el mismo de la pestaña de métricas.
    """
    error_pct = _error_tipico_pct(producto)
    pedido = max(total - stock, 0)
    con_colchon = max(total * (1 + error_pct / 100) - stock, 0)
    if pedido == 0:
        detalle = (
            f"Con {stock:,.0f} galones en el tanque alcanza para cubrir los "
            f"{total:,.0f} galones estimados: <b>no hace falta pedir</b>."
        )
    else:
        detalle = (
            f"Se venderían {total:,.0f} galones y ya hay {stock:,.0f} en el tanque."
        )
    return (
        '<div class="pedido">'
        '<div class="pedido-titulo"><i class="bi bi-truck"></i> Pedido sugerido</div>'
        f'<div class="cifra">{pedido:,.0f}<span class="unidad">galones</span></div>'
        f'<div class="msg-cuerpo">{detalle}</div>'
        f'<div class="msg-pie">Con colchón de seguridad (+{error_pct:.0f} %, el error '
        f"típico del modelo): <b>{con_colchon:,.0f} galones</b>.</div>"
        "</div>"
    )


def galones_validos(valor: float | None) -> int:
    """Vacío o negativo → 0. No existe un tanque con galones negativos."""
    return max(int(valor or 0), 0)


def _plan_html(plan: dict) -> str:
    """Bloque "Plan de entregas": qué días recibir combustible y cuánto."""
    if not plan["entregas"]:
        cuerpo = (
            '<div class="msg-cuerpo">Con el stock actual alcanza para todo el rango: '
            "<b>no hace falta pedir</b>.</div>"
        )
    else:
        items = "".join(
            f"<li><b>{fecha_larga(e['fecha'])}</b>: recibir "
            f"<b>{e['entrega']:,.0f} galones</b> (el tanque tendría "
            f"{e['stock_al_abrir']:,.0f} al abrir)</li>"
            for e in plan["entregas"]
        )
        cuerpo = (
            f'<div class="cifra">{plan["total_pedido"]:,.0f}'
            f'<span class="unidad">galones en {len(plan["entregas"])} '
            "entrega(s)</span></div>"
            f'<ul class="msg-detalle">{items}</ul>'
        )
    return (
        '<div class="pedido">'
        '<div class="pedido-titulo"><i class="bi bi-truck"></i> Plan de entregas</div>'
        f"{cuerpo}"
        '<div class="msg-pie">Cada entrega llena el tanque hasta '
        f"{plan['tope']:,.0f} galones y llega antes de abrir; si el proveedor demora, "
        "llámalo con anticipación. Al final del rango quedarían "
        f"{plan['stock_final']:,.0f} galones en el tanque.</div>"
        "</div>"
    )


def predecir_rango_ui(
    producto: str,
    fecha_inicio_str: str,
    dias: int,
    stock: float | None,
    capacidad: float | None,
    llenado_max: float,
    stock_minimo: float | None,
):
    r, error = _ejecutar(predecir_rango, producto, fecha_inicio_str, int(dias))
    if error:
        return None, error, None

    tabla = pd.DataFrame(r["predicciones"])[["fecha", "prediccion_galones"]]
    tabla["fecha"] = tabla["fecha"].astype(str)
    tabla = tabla.rename(columns={"prediccion_galones": "galones"})
    total = float(tabla["galones"].sum())
    stock = galones_validos(stock)

    # Sin capacidad: un solo pedido (venta − stock). Con capacidad: plan de entregas
    # día por día, porque puede que todo lo necesario no quepa de una vez.
    plan = None
    if galones_validos(capacidad) > 0:
        try:
            plan = planificar_entregas(
                [(p["fecha"], p["prediccion_galones"]) for p in r["predicciones"]],
                stock_inicial=stock,
                capacidad=galones_validos(capacidad),
                llenado_max_pct=llenado_max,
                stock_minimo=galones_validos(stock_minimo),
            )
            bloque_pedido = _plan_html(plan)
        except PlanImposible as e:
            bloque_pedido = (
                '<div class="pedido"><div class="pedido-titulo">'
                '<i class="bi bi-exclamation-triangle"></i> No se pudo armar el plan '
                f'de entregas</div><div class="msg-cuerpo">{e}</div></div>'
            )
    else:
        bloque_pedido = _pedido_html(total, stock, r["producto"])

    cuerpo = (
        f'<div class="cifra">{total:,.0f}'
        '<span class="unidad">galones en total</span></div>'
        '<ul class="msg-detalle">'
        f"<li><b>Promedio por día:</b> {total / len(tabla):,.0f} galones</li>"
        f"{_items_contexto(r)}"
        "</ul>"
        f"{bloque_pedido}"
    ) + notas_html(r["notas"])

    resumen = banner(
        "ok",
        "calendar-range",
        f"{r['producto']} — {r['dias']} días desde el {fecha_larga(r['fecha_inicio'])}",
        cuerpo,
    )

    # El gráfico necesita la fecha ISO para ordenar el eje; la tabla la muestra larga.
    if plan:
        # Con plan, el detalle muestra cómo se mueve el tanque cada día.
        detalle = pd.DataFrame(
            {
                "fecha": [fecha_larga(d["fecha"]) for d in plan["dias"]],
                "stock al abrir": [round(d["stock_al_abrir"]) for d in plan["dias"]],
                "entrega": [round(d["entrega"]) for d in plan["dias"]],
                "venta estimada": [round(d["venta"]) for d in plan["dias"]],
                "stock al cerrar": [round(d["stock_al_cerrar"]) for d in plan["dias"]],
            }
        )
    else:
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
def _ventas_promedio(productos: list[str], hasta: date) -> dict:
    """Venta diaria promedio de cada producto en los 90 días evaluados."""
    try:
        db = SessionLocal()
        try:
            return {p: venta_promedio_diaria(db, p, hasta) for p in productos}
        finally:
            db.close()
    except Exception:
        return {}


def cargar_metricas_ui():
    """Métricas explicadas para alguien que no es estadístico.

    Un error de 138 galones suena enorme si no se sabe cuánto se vende: por eso cada
    error va al lado de la venta diaria del producto y en %. Y en vez de "MAPE" o
    "MASE" se compara con lo que haría una persona sin modelo: pedir lo mismo que se
    vendió el mismo día de la semana pasada.
    """
    m = metricas_modelo()
    entrenado = date.fromisoformat(m["fecha_entrenamiento"])
    ventas = _ventas_promedio([f["producto"] for f in m["metricas"]], entrenado)

    filas_html = ""
    filas_tabla = []
    for f in m["metricas"]:
        venta = ventas.get(f["producto"])
        escala = f" de unos {venta:,.0f} que se venden" if venta else ""
        filas_html += (
            f"<li><b>{f['producto']}</b>: se equivoca en promedio "
            f"{f['error_medio_galones']:,.0f} galones al día{escala} "
            f"(≈ {f['mape']:.0f} de cada 100 galones). Se equivoca "
            f"<b>{f['mejora_vs_simple_pct']:.0f} % menos</b> que repetir la venta de "
            "la semana pasada.</li>"
        )
        filas_tabla.append(
            {
                "Producto": f["producto"],
                "Venta promedio (gal/día)": round(venta) if venta else None,
                "Error medio (gal/día)": f["error_medio_galones"],
                "Error medio (%)": f["mape"],
                "Mejora vs. método simple (%)": f["mejora_vs_simple_pct"],
            }
        )

    cuerpo = (
        '<div class="msg-cuerpo">Se le pidió al modelo predecir <b>90 días cuyas '
        "ventas reales ya se conocían</b> (sin mostrárselas) y luego se comparó día "
        "por día lo que dijo con lo que de verdad se vendió:</div>"
        f'<ul class="msg-detalle">{filas_html}</ul>'
        '<div class="msg-pie"><b>Error medio</b>: cuánto se aleja la predicción de '
        "la venta real en un día cualquiera; unos días se pasa y otros se queda "
        "corto. · <b>Método simple</b>: pedir lo mismo que se vendió el mismo día de "
        "la semana pasada, que es lo que se haría sin el sistema.</div>"
    )
    titulo = "¿Qué tan bien predice el modelo?"
    return banner("info", "bar-chart", titulo, cuerpo), pd.DataFrame(filas_tabla)


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
            # Opcional: con el stock, el resumen dice cuánto pedir (venta − stock);
            # si además se indica la capacidad, arma un plan de entregas día por día.
            # Sin `minimum=0` a propósito: con él, Gradio deja escribir -5 igual y
            # recién al predecir lanza un error en inglés. En su lugar, al salir del
            # campo (blur) un negativo o vacío se corrige a 0 a la vista del usuario.
            with gr.Accordion("Tanque y pedido (opcional)", open=True):
                with gr.Row(equal_height=True):
                    r_stock = gr.Number(
                        value=0,
                        precision=0,
                        label="Stock al inicio del rango (galones)",
                        info="Lo que hay en el tanque el primer día del rango.",
                    )
                    r_capacidad = gr.Number(
                        value=0,
                        precision=0,
                        label="Capacidad del tanque (galones)",
                        info="Si la dejas en 0, se sugiere un solo pedido.",
                    )
                    r_llenado = gr.Slider(
                        80,
                        100,
                        value=95,
                        step=1,
                        label="Llenado máximo (%)",
                        info="Los tanques no se llenan al 100 %: el combustible se "
                        "dilata (GLP ≈ 85 %).",
                    )
                    r_minimo = gr.Number(
                        value=0,
                        precision=0,
                        label="Stock mínimo (galones)",
                        info="Reserva que nunca se toca: cubre errores y demoras.",
                    )
            for campo in (r_stock, r_capacidad, r_minimo):
                campo.blur(
                    galones_validos,
                    inputs=campo,
                    outputs=campo,
                    show_progress="hidden",
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
                    inputs=[
                        r_producto,
                        r_fecha,
                        r_dias,
                        r_stock,
                        r_capacidad,
                        r_llenado,
                        r_minimo,
                    ],
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
