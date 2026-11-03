import tempfile
from datetime import date, timedelta, datetime
from pathlib import Path

import gradio as gr
import pandas as pd

from app.database import SessionLocal
from app.services.auth import registrar_accion
from app.services.entregas import (
    DIAS_SEMANA,
    PlanImposible,
    ReglasPedido,
    capacidad_cisterna,
    planificar_entregas,
    validar_tanque,
)
from app.services.prediccion.features import HistorialInsuficiente
from app.services.prediccion.ingesta import (
    ArchivoInvalido,
    guardar_reporte,
    leer_reporte,
    ultimo_dia_registrado,
)
from app.services.prediccion.servicio import (
    MAX_HORIZONTE_DIAS,
    FechaEnPasado,
    ProductoNoServido,
    margen_error_galones,
    metricas_modelo,
    predecir_dia,
    predecir_rango,
    ultimo_dia_historial,
    venta_promedio_diaria,
    verificacion_ultimo_mes,
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

# Mes de la prueba "Real vs. predicho" (verificacion_octubre.csv). Los calendarios de
# esa sección solo dejan elegir días dentro de este rango.
VERIF_DESDE = date(2026, 10, 1)
VERIF_HASTA = date(2026, 10, 30)

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
        # El botón no se toca aquí: lo decide `ajustar_rango` al cambiar la fecha,
        # porque además depende de los datos del tanque.
        gr.update(),
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
def _datos_completos(
    fecha_inicio: str | None, stock: float | None, capacidad: float | None
) -> bool:
    """"Predecir rango" solo se habilita con fecha, galones actuales y capacidad.

    Los galones actuales pueden ser 0 (tanque vacío); la capacidad no.
    """
    return (
        bool(fecha_inicio)
        and stock is not None
        and stock >= 0
        and capacidad is not None
        and capacidad > 0
    )


def estado_boton(fecha_inicio: str | None, stock: float | None, capacidad: float | None):
    """Al escribir en los campos del tanque: habilita o deshabilita el botón."""
    return gr.update(interactive=_datos_completos(fecha_inicio, stock, capacidad))


def ajustar_rango(
    producto: str,
    fecha_inicio: str | None,
    dias: int,
    stock: float | None,
    capacidad: float | None,
):
    """Al cambiar la fecha de inicio: habilita "Predecir rango" y acota el slider.

    El slider no deja pedir días más allá del máximo del calendario (último día
    con ventas + MAX_HORIZONTE_DIAS). El botón además exige los datos del tanque.
    """
    ultimo = _ultimo_dia(producto)
    if not fecha_inicio or ultimo is None:
        return gr.update(interactive=False), gr.update(info=None)
    maximo = ultimo + timedelta(days=MAX_HORIZONTE_DIAS)
    dias_max = max((maximo - date.fromisoformat(fecha_inicio)).days + 1, 1)
    dias = min(int(dias), dias_max)
    return (
        gr.update(interactive=_datos_completos(fecha_inicio, stock, capacidad)),
        gr.update(maximum=dias_max, value=dias, info=texto_hasta(fecha_inicio, dias)),
    )


def texto_hasta(fecha_inicio: str | None, dias: int) -> str | None:
    """Texto bajo el slider: hasta qué día llega el pronóstico, sin contar a mano."""
    if not fecha_inicio:
        return None
    fin = date.fromisoformat(fecha_inicio) + timedelta(days=int(dias) - 1)
    return f"Pronóstico hasta el {fecha_larga(fin)}"


def actualizar_hasta(fecha_inicio: str | None, dias: int):
    """Al mover el slider: actualiza el texto "Pronóstico hasta el…"."""
    return gr.update(info=texto_hasta(fecha_inicio, dias))


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


def corregir_negativo(valor: float | None) -> int | None:
    """Al salir de un campo del tanque: negativo → 0, pero vacío sigue vacío.

    Vacío no se convierte en 0 porque los dos campos son obligatorios: un campo
    vacío tiene que seguir mostrándose vacío y mantener el botón deshabilitado.
    """
    return None if valor is None else galones_validos(valor)


def _sin_anio(d: date) -> str:
    """2026-11-01 → "1 de noviembre" (para no repetir el año en un mismo texto)."""
    return fecha_larga(d).rsplit(" de ", 1)[0]


def _hora_en_palabras(hora) -> str:
    """15:00 → "las 3 de la tarde"; 9:00 → "las 9 de la mañana"."""
    momento = "de la tarde" if hora.hour >= 12 else "de la mañana"
    return f"las {hora.hour % 12 or 12} {momento}"


def _plan_html(plan: dict, ahora: datetime) -> str:
    """Bloque "Plan de entregas": solo qué día pedir y cuántos galones.

    El día en que el pedido queda disponible está en la tabla de detalle, para no
    recargar el resumen.
    """
    if not plan["entregas"] and not plan["alertas"]:
        cuerpo = (
            '<div class="msg-cuerpo"><b>No hace falta pedir:</b> el stock actual '
            "alcanza para todo el rango.</div>"
        )
    else:
        items = "".join(
            f"<li>Pedir <b>{e['entrega']:,.0f} gal.</b> el "
            f"<b>{DIAS_SEMANA[e['pagar_antes_de'].weekday()]} "
            f"{_sin_anio(e['pagar_antes_de'].date())}</b></li>"
            for e in plan["entregas"]
        )
        cuerpo = f'<ul class="msg-detalle">{items}</ul>' if items else ""

    # Fuera del if/else: puede faltar combustible aunque ya no se alcance a pedir.
    if plan["alertas"]:
        dias_mal = ", ".join(_sin_anio(d["fecha"]) for d in plan["alertas"])
        llegada = ReglasPedido().hora_llegada(ahora)
        cuerpo += (
            f'<div class="msg-pie"><b>Atención:</b> para el {dias_mal} ya pasó la hora '
            "de pago. Contactar con el proveedor lo antes posible </div>"
        )

    return (
        '<div class="pedido">'
            '<div class="pedido-titulo"><i class="bi bi-truck"></i> Plan de entregas</div>'
            f"{cuerpo}"
        '</div>'
    )


def _hoja_pedidos(plan: dict | None, error_plan: str) -> pd.DataFrame:
    """Hoja "Pedidos": lo que el administrador tiene que hacer, un pedido por fila.

    Es lo más útil del reporte (cuándo pagar y cuánto), por eso va primera. Los días
    cuya hora de pago ya pasó también aparecen, para que llame al proveedor.
    """
    if plan is None:
        return pd.DataFrame({"Aviso": [f"No se pudo armar el plan de entregas: {error_plan}"]})

    filas = [
        {
            "Pagar el pedido": fecha_larga(e["pagar_antes_de"].date()),
            "Hasta las": f"{e['pagar_antes_de']:%H:%M}",
            "Galones a pedir": round(e["entrega"]),
            "Disponible desde": fecha_larga(e["fecha"]),
        }
        for e in plan["entregas"]
    ]
    filas += [
        {
            "Pagar el pedido": "Ya pasó la hora de pago: llamar al proveedor hoy",
            "Hasta las": "—",
            "Galones a pedir": None,
            "Disponible desde": fecha_larga(d["fecha"]),
        }
        for d in plan["alertas"]
    ]
    if not filas:
        return pd.DataFrame(
            {"Aviso": ["No hace falta pedir: el stock actual alcanza para todo el rango."]}
        )
    return pd.DataFrame(filas)


def _reporte_excel(
    r: dict,
    total: float,
    stock: int,
    capacidad: int,
    margen: float,
    plan: dict | None,
    error_plan: str,
    detalle: pd.DataFrame,
) -> str:
    """Guarda el resultado del rango en un .xlsx y devuelve su ruta.

    Tres hojas: "Pedidos" (cuándo pagar y cuántos galones), "Resumen" (las cifras
    del recuadro verde) y "Detalle" (la misma tabla que se ve en pantalla). Cada
    archivo va en su propia carpeta temporal para que dos usuarios prediciendo a la
    vez no se pisen el archivo.
    """
    resumen = pd.DataFrame(
        {
            "Concepto": [
                "Producto",
                "Fecha de inicio",
                "Días predichos",
                "Total a pedir (galones)",
                "Pedidos (un camión cada uno)",
                "Capacidad del camión (galones)",
                "Venta estimada en el rango (galones)",
                "Venta promedio por día (galones)",
                "Margen de error por día (± galones)",
                "Galones en el tanque al inicio",
                "Capacidad del tanque (galones)",
                "Precio considerado (S/ por galón)",
                "Ventas cargadas hasta",
                "Reporte generado",
            ],
            "Valor": [
                r["producto"],
                fecha_larga(r["fecha_inicio"]),
                r["dias"],
                round(plan["total_pedido"]) if plan else "—",
                len(plan["entregas"]) if plan else "—",
                capacidad_cisterna(r["producto"]),
                round(total),
                round(total / r["dias"]),
                round(margen),
                stock,
                capacidad,
                round(r["precio_referencia"], 2),
                fecha_larga(r["ultimo_dia_real"]),
                datetime.now().strftime("%d/%m/%Y %H:%M"),
            ],
        }
    )

    nombre = f"prediccion_{r['producto']}_{r['fecha_inicio']}_{r['dias']}dias.xlsx"
    ruta = Path(tempfile.mkdtemp()) / nombre
    hojas = (
        ("Pedidos", _hoja_pedidos(plan, error_plan)),
        ("Resumen", resumen),
        ("Detalle", detalle),
    )
    with pd.ExcelWriter(ruta) as excel:
        for hoja, df in hojas:
            df.to_excel(excel, sheet_name=hoja, index=False)
            # Ancho de cada columna según su texto más largo, para que se lea al abrir.
            ws = excel.sheets[hoja]
            for i, col in enumerate(df.columns):
                largo = max([len(str(col)), *df[col].astype(str).str.len()])
                ws.column_dimensions[chr(65 + i)].width = largo + 2
    return str(ruta)


def predecir_rango_ui(
    producto: str,
    fecha_inicio_str: str,
    dias: int,
    stock: float | None,
    capacidad: float | None
):
    # Datos del tanque imposibles: se corta ANTES de predecir. No tiene sentido
    # mostrar un pronóstico ni una tabla armados sobre un tanque que no existe.
    try:
        validar_tanque(producto, galones_validos(stock), galones_validos(capacidad))
    except PlanImposible as e:
        error = error_html("Revisa los datos del tanque", str(e))
        return None, error, None, gr.update(value=None, visible=False)

    r, error = _ejecutar(predecir_rango, producto, fecha_inicio_str, int(dias))
    if error:
        return None, error, None, gr.update(value=None, visible=False)

    tabla = pd.DataFrame(r["predicciones"])[["fecha", "prediccion_galones"]]
    tabla["fecha"] = tabla["fecha"].astype(str)
    tabla = tabla.rename(columns={"prediccion_galones": "galones"})
    total = float(tabla["galones"].sum())
    stock = galones_validos(stock)

    # Margen ± en galones por día (prueba de octubre). Mínimo y máximo de cada día;
    # el mínimo no baja de 0 porque no existen ventas negativas.
    margen = margen_error_galones(r["producto"])
    tabla["mínimo"] = (tabla["galones"] - margen).clip(lower=0)
    tabla["máximo"] = tabla["galones"] + margen
    promedio = total / len(tabla)

    # Sin capacidad: un solo pedido (venta − stock). Con capacidad: plan de entregas
    # día por día, porque puede que todo lo necesario no quepa de una vez.
    # El plan usa la venta ESTIMADA, sin sumarle el margen: en la prueba de octubre
    # el total del mes casi no se desvió (GLP −1 %, REGULAR 0 %, PREMIUM +7 %) y la
    # reserva mínima del tanque (entregas.py) cubre los días en que se vende más.
    # Sumar además el margen inflaría los pedidos.
    plan = None
    error_plan = ""
    ahora = datetime.now()
    if galones_validos(capacidad) > 0:
        try:
            plan = planificar_entregas(
                r["producto"],
                [(p["fecha"], p["prediccion_galones"]) for p in r["predicciones"]],
                stock_inicial=stock,
                capacidad=galones_validos(capacidad),
                ahora=ahora,
            )
            bloque_pedido = _plan_html(plan, ahora)
        except PlanImposible as e:
            error_plan = str(e)
            pie = f'<div class="msg-pie">{e.detalle}</div>' if e.detalle else ""
            bloque_pedido = (
                '<div class="pedido"><div class="pedido-titulo">'
                '<i class="bi bi-exclamation-triangle"></i> No se pudo armar el plan '
                f'de entregas</div><div class="msg-cuerpo">{e}</div>{pie}</div>'
            )
    else:
        bloque_pedido = _pedido_html(total, stock, r["producto"])

    # Solo lo que el administrador usa para decidir: qué pedir y cuándo, y tres datos
    # de contexto. Los totales y promedios quedan en la tabla de detalle y el Excel.
    cuerpo = (
        f"{bloque_pedido}"
        '<div class="msg-cuerpo"><b>Información</b></div>'
        '<ul class="msg-detalle">'
        f"<li>Realizar los pedidos antes de "
        f"{_hora_en_palabras(ReglasPedido().hora_limite_pago)}.</li>"
        f"<li>Cada pedido es como máximo un camión de "
        f"{capacidad_cisterna(r['producto']):,.0f} galones"
        f"{'' if r['producto'] == 'GLP' else ' (puede compartirlo con otros combustibles)'}"
        ".</li>"
        f"<li>Precio considerado: S/ {r['precio_referencia']:.2f} por galón</li>"
        f"<li>Margen de error: ± {margen:,.0f} galones por día</li>"
        "</ul>"
    ) + notas_html(r["notas"])

    inicio = date.fromisoformat(str(r["fecha_inicio"]))
    fin = inicio + timedelta(days=r["dias"] - 1)
    desde = _sin_anio(inicio) if inicio.year == fin.year else fecha_larga(inicio)
    resumen = banner(
        "ok",
        "calendar-range",
        f"{r['producto']} — {r['dias']} días, del {desde} al {fecha_larga(fin)}",
        cuerpo,
    )

    # Gráfico: tres líneas (estimado, mínimo, máximo). Necesita la fecha ISO para
    # ordenar el eje; la tabla la muestra larga.
    grafico = tabla.rename(columns={"galones": "estimado"}).melt(
        id_vars="fecha", var_name="serie", value_name="galones"
    )

    ventas = pd.DataFrame(
        {
            "Fecha": tabla["fecha"].map(fecha_larga),
            "Demanda estimada (gal)": tabla["galones"].round(),
            "Mínimo (gal)": tabla["mínimo"].round(),
            "Máximo (gal)": tabla["máximo"].round(),
        }
    )
    if plan:
        # Con plan, el detalle muestra además cómo se mueve el tanque cada día, en el
        # orden en que se lee: stock inicial + pedido − demanda = stock final.
        # "Pedido" son los galones que llegan ese día (ya están al abrir); qué día
        # pagarlos lo dice el plan de entregas del resumen.
        dias = plan["dias"]
        detalle_excel = pd.DataFrame(
            {
                "Fecha": ventas["Fecha"],
                "Stock inicial (gal)": [round(d["stock_al_abrir"]) for d in dias],
                "Pedido (gal)": [round(d["entrega"]) or None for d in dias],
                "Demanda estimada (gal)": ventas["Demanda estimada (gal)"],
                "Mínimo (gal)": ventas["Mínimo (gal)"],
                "Máximo (gal)": ventas["Máximo (gal)"],
                "Stock final (gal)": [round(d["stock_al_cerrar"]) for d in dias],
            }
        )
        # En pantalla el pedido va como "+2,421" (se suma al tanque); en el Excel
        # queda como número para poder sumarlo.
        detalle = detalle_excel.assign(
            **{
                "Pedido (gal)": [
                    f"+{d['entrega']:,.0f}" if d["entrega"] > 0 else "" for d in dias
                ]
            }
        )
    else:
        detalle = detalle_excel = ventas

    excel = _reporte_excel(
        r,
        total,
        stock,
        galones_validos(capacidad),
        margen,
        plan,
        error_plan,
        detalle_excel,
    )
    return grafico, resumen, detalle, gr.update(value=excel, visible=True)


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


def info_carga_md() -> str:
    """Texto de la pestaña de carga con el último día registrado (al abrir y tras subir)."""
    try:
        db = SessionLocal()
        try:
            ultimo = ultimo_dia_registrado(db)
        finally:
            db.close()
    except Exception:
        ultimo = None
    texto = fecha_larga(ultimo) if ultimo else "todavía no hay ventas cargadas"
    return (
        "Sube el **reporte de ventas** (`.xlsx`) que exporta el sistema "
        "del grifo.  \n"
        f"Último día registrado: **{texto}**\n\n"
        "Puedes subir un día, un mes o varios meses a la vez."
    )


def cargar_xlsx_ui(archivos, request: gr.Request, progress=gr.Progress()):
    """Carga uno o varios reportes mensuales .xlsx en el historial del modelo.

    Gradio pasa ``request`` solo (por la anotación de tipo); de ahí sale el usuario
    con sesión iniciada, para dejar en ``usuarios.accion`` qué rango cargó.
    """
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
    rango = []  # fechas inicio/fin de los archivos que sí se guardaron

    def _error(nombre, mensaje):
        lineas.append(
            f'<li><span class="ico-err">✕</span> <b>{nombre}</b>: {mensaje}</li>'
        )

    # Paso 1: leer todos los archivos (sin tocar la base). Cada reporte debe empezar
    # el día siguiente al último registrado, así que hay que guardarlos en orden de
    # fechas. El nombre o la ruta temporal que entrega Gradio no lo garantizan: se
    # ordena por la primera fecha real de cada archivo.
    leidos = []  # (fecha_inicio, nombre, df)
    for ruta in progress.tqdm(archivos, desc="Leyendo"):
        nombre = str(ruta).replace("\\", "/").split("/")[-1]
        try:
            with open(ruta, "rb") as f:
                df = leer_reporte(f.read())
        except (ArchivoInvalido, ValueError) as e:
            con_error += 1
            _error(nombre, e)
            continue
        except Exception as e:  # noqa: BLE001 - se reporta por archivo
            con_error += 1
            _error(nombre, f"error inesperado: {e}")
            continue
        leidos.append((df["fecha"].min(), nombre, df))
    leidos.sort(key=lambda x: x[0])

    # Paso 2: guardar en orden cronológico.
    try:
        for _, nombre, df in progress.tqdm(leidos, desc="Guardando"):
            try:
                r = guardar_reporte(db, df)
            except (ArchivoInvalido, ValueError) as e:
                con_error += 1
                _error(nombre, e)
                continue
            except Exception as e:  # noqa: BLE001 - se reporta por archivo
                db.rollback()
                con_error += 1
                _error(nombre, f"error inesperado: {e}")
                continue

            total += r["filas_guardadas"]
            rango += [r["fecha_inicio"], r["fecha_fin"]]
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

        # Deja registrado quién cargó y qué rango (si hubo sesión y algo se guardó).
        usuario = getattr(request, "username", None)
        if rango and usuario:
            try:
                registrar_accion(
                    usuario,
                    f"Cargó las ventas del {min(rango):%d/%m/%Y} al "
                    f"{max(rango):%d/%m/%Y} ({datetime.now():%d/%m/%Y %H:%M})",
                    db,
                )
            except Exception:  # noqa: BLE001 - no debe tumbar una carga ya guardada
                db.rollback()
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
    """Tabla de error del modelo por producto, al lado de su venta diaria.

    Un error de 138 galones suena enorme si no se sabe cuánto se vende: por eso cada
    error va al lado de la venta diaria del producto y en %. La mejora se mide contra
    lo que haría una persona sin modelo: pedir lo mismo que se vendió el mismo día de
    la semana pasada.
    """
    m = metricas_modelo()
    entrenado = date.fromisoformat(m["fecha_entrenamiento"])
    ventas = _ventas_promedio([f["producto"] for f in m["metricas"]], entrenado)

    filas_tabla = []
    for f in m["metricas"]:
        venta = ventas.get(f["producto"])
        filas_tabla.append(
            {
                "Producto": f["producto"],
                "Venta promedio (gal/día)": round(venta) if venta else None,
                "Error medio (gal/día)": f["error_medio_galones"],
                "Error medio (%)": f["mape"],
                "Mejora vs. método simple (%)": f["mejora_vs_simple_pct"],
            }
        )
    return pd.DataFrame(filas_tabla)


def comparacion_ui(producto: str, desde: str | None, hasta: str | None):
    """Real vs. predicho de octubre, filtrado por producto y fechas."""
    d = date.fromisoformat(desde[:10]) if desde else VERIF_DESDE
    h = date.fromisoformat(hasta[:10]) if hasta else VERIF_HASTA
    t = verificacion_ultimo_mes(producto, d, h)

    grafico = t.melt(id_vars="fecha", value_vars=["real", "predicho"],
                     var_name="serie", value_name="galones")
    tabla = pd.DataFrame({
        "Fecha": t["fecha"].dt.strftime("%d/%m/%Y"),
        "Real (gal)": t["real"].round(0),
        "Predicho (gal)": t["predicho"].round(0),
        "Diferencia (gal)": t["real_menos_predicho"].round(0),
        "Diferencia (%)": t["error_pct"].round(1),
    })
    return grafico, tabla


with gr.Blocks(title="Inicio") as demo:
    gr.HTML(ENCABEZADO_HTML, js_on_load=ENCABEZADO_JS_ON_LOAD)

    with gr.Tabs() as pestanas:
        

        # ---------------- Predicción de rango ----------------
        with gr.Tab("Predicción", id="rango"):
            # Clase "aviso-vacio-oculto" (estilos.css): sin aviso no ocupa espacio.
            r_aviso = gr.HTML(js_on_load=IR_CARGA_JS, elem_classes="aviso-vacio-oculto")
            
            
            with gr.Row(equal_height=True):
                r_producto = gr.Dropdown(PRODUCTOS, value="REGULAR", label="Combustible", info="Seleccione un combustible")
                r_fecha = calendario("Seleccione la fecha de inicio")
                r_dias = gr.Slider(
                    1, MAX_HORIZONTE_DIAS, value=7, step=1, label="Cantidad de días a predecir"
                )
            # Obligatorios: con los dos, el resumen arma el plan de entregas día por
            # día. Empiezan vacíos y "Predecir rango" sigue deshabilitado hasta que
            # se llenen (ver `_datos_completos`).
            # Sin `minimum=0` a propósito: con él, Gradio deja escribir -5 igual y
            # recién al predecir lanza un error en inglés. En su lugar, al salir del
            # campo (blur) un negativo se corrige a 0 a la vista del usuario.
            with gr.Row(equal_height=True):
                r_stock = gr.Number(
                    value=None,
                    precision=0,
                    label="Galones actuales en el tanque",
                )
                r_capacidad = gr.Number(
                    value=None,
                    precision=0,
                    label="Capacidad del tanque (galones)",
                )
            for campo in (r_stock, r_capacidad):
                campo.blur(
                    corregir_negativo,
                    inputs=campo,
                    outputs=campo,
                    show_progress="hidden",
                )
            r_boton = gr.Button(
                "Predecir rango", variant="primary", size="lg", interactive=False
            )
            r_resumen = gr.HTML(js_on_load=IR_CARGA_JS)
            r_grafico = gr.LinePlot(
                x="fecha",
                y="galones",
                color="serie",  # estimado, mínimo y máximo
                label="Predicción (galones/día)",
            )
            r_tabla = gr.Dataframe(label="Detalle")
            # Oculto hasta la primera predicción: antes no hay nada que descargar.
            r_excel = gr.DownloadButton(
                "Descargar reporte en Excel",
                variant="secondary",
                visible=False,
                elem_classes="boton-excel",
            )

            r_producto.change(
                limites_fecha, inputs=r_producto, outputs=[r_fecha, r_aviso, r_boton]
            )
            r_fecha.change(
                ajustar_rango,
                inputs=[r_producto, r_fecha, r_dias, r_stock, r_capacidad],
                outputs=[r_boton, r_dias],
                show_progress="hidden",
            )
            r_dias.change(
                actualizar_hasta,
                inputs=[r_fecha, r_dias],
                outputs=r_dias,
                show_progress="hidden",
            )
            for campo in (r_stock, r_capacidad):
                campo.change(
                    estado_boton,
                    inputs=[r_fecha, r_stock, r_capacidad],
                    outputs=r_boton,
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
                    ],
                    outputs=[r_grafico, r_resumen, r_tabla, r_excel],
                    show_progress="full",
                )
                .then(
                    lambda f, s, c: gr.update(
                        value="Predecir rango",
                        interactive=_datos_completos(f, s, c),
                    ),
                    inputs=[r_fecha, r_stock, r_capacidad],
                    outputs=r_boton,
                    show_progress="hidden",
                )
            )

        # ---------------- Carga del reporte mensual ----------------
        with gr.Tab("Cargar reporte de ventas", id="carga"):
            v_info = gr.Markdown()  # se llena con info_carga_md (al abrir y tras subir)
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
                    inputs=r_producto,
                    outputs=[r_fecha, r_aviso, r_boton],
                    show_progress="hidden",
                )
                .then(info_carga_md, outputs=v_info, show_progress="hidden")
            )

        # ---------------- Métricas ----------------
        with gr.Tab("Métricas del modelo", id="metricas"):
            gr.Markdown(
                "### Real vs. predicho (octubre 2026)\n"
                "Para realizar esta verificación, el modelo se entrenó hasta el 30/09 y predijo "
                "octubre sin ver las ventas reales."
            )
            with gr.Row(equal_height=True):
                c_producto = gr.Dropdown(PRODUCTOS, value="REGULAR", label="Combustible")
                # Mismo calendario que Predicción; solo deja elegir días de octubre
                # (los que tiene verificacion_octubre.csv).
                c_desde = calendario("Desde", VERIF_DESDE.isoformat(),
                                     VERIF_DESDE.isoformat(), VERIF_HASTA.isoformat())
                c_hasta = calendario("Hasta", VERIF_HASTA.isoformat(),
                                     VERIF_DESDE.isoformat(), VERIF_HASTA.isoformat())
            
            c_grafico = gr.LinePlot(x="fecha", y="galones", color="serie",
                                    label="Real vs. predicho (galones/día)")

            c_tabla = gr.Dataframe(label="Detalle día por día")

            for comp in (c_producto, c_desde, c_hasta):
                comp.change(comparacion_ui, inputs=[c_producto, c_desde, c_hasta],
                            outputs=[c_grafico, c_tabla])

            m_tabla = gr.Dataframe(label="Detalle por combustible")
            m_boton = gr.Button("Actualizar métricas")
            m_boton.click(cargar_metricas_ui, outputs=m_tabla)

    # Al abrir la página: métricas y límites del calendario de rango (calculados en
    # cada visita, no al arrancar el servidor, para que "hoy" sea siempre hoy).
    demo.load(cargar_metricas_ui, outputs=m_tabla)
    demo.load(info_carga_md, outputs=v_info)
    demo.load(limites_fecha, inputs=r_producto, outputs=[r_fecha, r_aviso, r_boton])
    demo.load(comparacion_ui, inputs=[c_producto, c_desde, c_hasta], outputs=[c_grafico, c_tabla])

    # Botón "Cargar ventas" de los avisos y errores → pestaña de carga, sin salir de
    # la página.
    for html in (r_aviso, r_resumen):
        html.ir_carga(ir_a_carga, outputs=pestanas)
