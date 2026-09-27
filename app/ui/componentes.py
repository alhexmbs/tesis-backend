"""Piezas compartidas por las páginas Gradio: bloques HTML de mensaje y lectura de .js.

Las clases (`msg`, `msg-ok`, `cargando`, …) están en `static/estilos.css`.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"

# Hoja de estilos compartida por las tres apps montadas (login, registro, inicio).
CSS_PATH = STATIC_DIR / "estilos.css"

RELOJ_HTML = '<div class="reloj">🕒 <span id="reloj-inicio"></span></div>'

CERRAR_SESION_HTML = (
    '<div class="fila-cerrar-sesion">'
    '<a href="/inicio/logout" id="cerrar-sesion" class="boton-cerrar-sesion">'
    "⏻ Cerrar sesión</a>"
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
    """Bloque de color para los resultados. `tipo` es ok | err | info."""
    return (
        f'<div class="msg msg-{tipo}">'
        f'<div class="msg-titulo">{icono} {titulo}</div>'
        f"{cuerpo}"
        "</div>"
    )


def error_html(titulo: str, detalle: str = "") -> str:
    cuerpo = f'<div class="msg-cuerpo">{detalle}</div>' if detalle else ""
    return banner("err", "⚠️", titulo, cuerpo)


def notas_html(notas: list[str]) -> str:
    """Notas del servicio en lenguaje llano, para pegar al final del resumen."""
    if not notas:
        return ""
    items = "".join(f"<li>{n}</li>" for n in notas)
    return f'<ul class="msg-notas">{items}</ul>'
