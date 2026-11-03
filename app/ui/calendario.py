"""Campo de fecha con calendario (Flatpickr) para las pestañas de predicción.

Es un `gr.HTML` con tres datos ("props"):
- `value`:  fecha elegida, "AAAA-MM-DD" (o None). Es lo que recibe la función de
            Python cuando el calendario va en `inputs=`.
- `minimo`: primer día elegible (hoy).
- `maximo`: último día elegible (último día con ventas + MAX_HORIZONTE_DIAS).

Python los cambia devolviendo `gr.update(value=..., minimo=..., maximo=...)`; el
navegador (`static/js/calendario.js`) los aplica al calendario.
"""

import gradio as gr

from app.ui.componentes import leer_js

CALENDARIO_JS = leer_js("calendario.js")

# Flatpickr se sirve desde nuestra copia local (ver `main.py`, montaje "/vendor").
# Gradio carga este <head> antes de correr CALENDARIO_JS, y una sola vez aunque haya
# dos calendarios en la página.
CALENDARIO_HEAD = (
    '<link rel="stylesheet" href="/vendor/flatpickr/flatpickr.min.css">'
    '<script src="/vendor/flatpickr/flatpickr.min.js"></script>'
)

# No usa ${value}: así, al elegir una fecha, Gradio no redibuja el campo encima de
# Flatpickr. El texto visible lo pone Flatpickr ("29 de septiembre de 2026").
# La etiqueta se escribe en Python (ETIQUETA se reemplaza en `calendario()`), no
# como prop: cada gr.update(minimo=..., maximo=...) reemplaza TODOS los props, y un
# prop que no viene en el update deja de existir ("etiqueta is not defined").
CALENDARIO_TEMPLATE = """
<div class="campo-fecha">
  <span class="campo-etiqueta">ETIQUETA</span>
  <div class="campo-fecha-fila">
    <i class="bi bi-calendar3 campo-fecha-icono"></i>
    <input class="campo-fecha-input" type="text" placeholder="Elige una fecha">
  </div>
</div>
"""


def calendario(
    etiqueta: str,
    valor: str | None = None,
    minimo: str | None = None,
    maximo: str | None = None,
) -> gr.HTML:
    """Campo de fecha. Sin valor ni límites sale vacío y `limites_fecha` (inicio.py)
    lo llena al abrir; con límites fijos (fechas "AAAA-MM-DD") solo deja elegir
    días entre `minimo` y `maximo`."""
    return gr.HTML(
        value=valor,
        html_template=CALENDARIO_TEMPLATE.replace("ETIQUETA", etiqueta),
        js_on_load=CALENDARIO_JS,
        head=CALENDARIO_HEAD,
        minimo=minimo,
        maximo=maximo,
    )
