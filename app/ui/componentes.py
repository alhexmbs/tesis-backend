"""Piezas compartidas por las páginas Gradio: bloques HTML de mensaje y lectura de .js.

Las clases (`msg`, `msg-ok`, `cargando`, …) están en `static/estilos.css`.
"""

import re
from datetime import date
from pathlib import Path

import gradio as gr

STATIC_DIR = Path(__file__).parent / "static"

# Hoja de estilos compartida por las dos apps montadas (login, inicio).
CSS_PATH = STATIC_DIR / "estilos.css"

# Librerías de terceros copiadas en `static/vendor` (sin depender de internet).
VENDOR_DIR = STATIC_DIR / "vendor"

# Íconos de Bootstrap (`<i class="bi bi-...">`): se inyecta en el <head> de las dos
# páginas. Solo funcionan dentro de gr.HTML: pestañas, labels y botones son texto.
HEAD_ICONOS = (
    '<link rel="stylesheet" href="/vendor/bootstrap-icons/bootstrap-icons.min.css">'
)

# Tema compartido. La fuente por defecto de Gradio (Source Sans Pro) viene con el
# peso 600 recortado a unas pocas letras: en títulos, etiquetas y botones las que
# faltan (p. ej. la "A" o la "B") salen con otra fuente y se ven más chicas. Con
# fuentes del sistema (texto plano, sin archivo .woff2) todas las letras existen.
# `.set(...)`: las etiquetas de los campos ("Producto") van como texto simple, sin
# la pastilla azul que Soft les pone de fondo.
TEMA = gr.themes.Soft(
    primary_hue="blue",
    neutral_hue="slate",
    radius_size="lg",
    font=["Segoe UI", "system-ui", "-apple-system", "Roboto", "sans-serif"],
    font_mono=["Consolas", "ui-monospace", "monospace"],
).set(
    block_title_background_fill="transparent",
    block_title_padding="0",
    block_title_text_color="*neutral_700",
    block_title_text_weight="600",
    block_label_background_fill="transparent",
    block_label_text_color="*neutral_700",
)

# Encabezado de /inicio: nombre a la izquierda; fecha de hoy (la pone encabezado.js)
# y "Cerrar sesión" a la derecha.
ENCABEZADO_HTML = (
    '<div class="encabezado">'
    "<div>"
    '<div class="encabezado-titulo">'
    '<i class="bi bi-fuel-pump"></i> BENZIN AI</div>'
    '<div class="encabezado-sub">Predicción de demanda de combustible vehicular</div>'
    "</div>"
    '<div class="encabezado-derecha">'
    '<span id="fecha-hoy" class="encabezado-fecha"></span>'
    '<a href="/inicio/logout" id="cerrar-sesion" class="boton-cerrar-sesion">'
    '<i class="bi bi-box-arrow-right"></i> Cerrar sesión</a>'
    "</div>"
    "</div>"
)

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip

# Fecha escrita como 2026-08-31 dentro de un texto.
FECHA_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def fecha_larga(d: date | str) -> str:
    """2026-08-31 → "31 de agosto de 2026" (sin depender del idioma del sistema)."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def cabecera_tarjeta(subtitulo: str) -> str:
    """Logo + nombre + subtítulo, arriba de la tarjeta de login."""
    return (
        '<div class="tarjeta-cabecera">'
        '<div class="tarjeta-logo"><i class="bi bi-fuel-pump"></i></div>'
        '<div class="tarjeta-titulo">BENZIN AI</div>'
        f'<div class="tarjeta-sub">{subtitulo}</div>'
        "</div>"
    )


SPINNER_HTML = (
    '<div class="cargando">'
    '<span class="cargando-circulo"></span>'
    "<span>Procesando los reportes… no cierres esta página.</span>"
    "</div>"
)


def leer_js(nombre: str) -> str:
    """Contenido de un .js de `app/ui/static/js`.

    Los parámetros `js=` y `js_on_load=` de Gradio solo aceptan el código como
    string (no hay `js_paths`), así que el archivo se lee al importar.
    """
    return (STATIC_DIR / "js" / nombre).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Mensajes en bloque de color
# --------------------------------------------------------------------------- #
def banner(tipo: str, icono: str, titulo: str, cuerpo: str = "") -> str:
    """Bloque de color para los resultados.

    `tipo` es ok | err | info; `icono` es el nombre de un ícono de Bootstrap sin el
    prefijo "bi-" (p. ej. "check-circle"): https://icons.getbootstrap.com
    """
    return (
        f'<div class="msg msg-{tipo}">'
        f'<div class="msg-titulo"><i class="bi bi-{icono}"></i> {titulo}</div>'
        f"{cuerpo}"
        "</div>"
    )


def error_html(titulo: str, detalle: str = "") -> str:
    cuerpo = f'<div class="msg-cuerpo">{detalle}</div>' if detalle else ""
    return banner("err", "exclamation-triangle", titulo, cuerpo)


def notas_html(notas: list[str]) -> str:
    """Notas del servicio en lenguaje llano, para pegar al final del resumen.

    El servicio escribe las fechas como 2026-08-31 (también las usa la API); aquí se
    muestran como "31 de agosto de 2026".
    """
    if not notas:
        return ""
    items = ""
    for nota in notas:
        nota = FECHA_ISO.sub(lambda m: fecha_larga(m.group()), nota)
        items += f"<li>{nota}</li>"
    return f'<ul class="msg-notas">{items}</ul>'
