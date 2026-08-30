import gradio as gr

from app.database import SessionLocal
from app.services.etl.pipeline import procesar_solo_ventas

RELOJ_HTML = '<div style="font-size:1.1em;">🕒 <span id="reloj-inicio"></span></div>'

RELOJ_JS_ON_LOAD = """
function actualizarReloj() {
    const el = element.querySelector('#reloj-inicio');
    if (el) {
        el.textContent = new Date().toLocaleString('es-PE');
    }
}
actualizarReloj();
setInterval(actualizarReloj, 1000);
"""

CERRAR_SESION_HTML = '<a href="/inicio/logout" id="cerrar-sesion">Cerrar sesión</a>'

CERRAR_SESION_JS_ON_LOAD = """
const link = element.querySelector('#cerrar-sesion');
if (link) {
    link.addEventListener('click', function (e) {
        e.preventDefault();
        fetch('/inicio/logout').finally(function () {
            window.location.href = '/login';
        });
    });
}
"""


def procesar_archivo_subido(archivo_path):
    if archivo_path is None:
        return "❌ Selecciona un archivo .txt primero."

    db = SessionLocal()
    try:
        with open(archivo_path, "rb") as f:
            contenido = f.read()
        resultado = procesar_solo_ventas(contenido, archivo_path, db)
    except Exception as e:
        return f"❌ {e}"
    finally:
        db.close()

    return (
        f"✅ Se procesaron {resultado['filas_procesadas']} filas "
        f"({resultado['fecha_inicio']} a {resultado['fecha_fin']})."
    )


with gr.Blocks(title="Inicio") as demo:
    gr.Markdown("# Bienvenido a BENZIN AI")
    gr.HTML(RELOJ_HTML, js_on_load=RELOJ_JS_ON_LOAD)

    gr.Markdown("### Nivel actual de los depósitos (galones)")
    with gr.Row():
        nivel_regular = gr.Number(label="Regular")
        nivel_premium = gr.Number(label="Premium")
        nivel_biodiesel = gr.Number(label="Biodiesel")
        nivel_glp = gr.Number(label="GLP")

    gr.Markdown("### Módulos")
    gr.Markdown(
        "- [Subir archivo de ventas](/inicio/subir_archivo)\n"
        "- [Ver predicciones](/inicio/ver_predicciones)\n"
        "- [Gráficos de tendencias](/inicio/graficos)"
    )

    gr.HTML(CERRAR_SESION_HTML, js_on_load=CERRAR_SESION_JS_ON_LOAD)


with demo.route("Subir archivo", "/subir_archivo"):
    gr.Markdown("## Subir archivo de ventas (.txt)")

    archivo = gr.File(label="Archivo de ventas", file_types=[".txt"])
    boton_subir = gr.Button("Procesar archivo", variant="primary")
    resultado_subida = gr.Markdown()

    boton_subir.click(
        fn=procesar_archivo_subido, inputs=archivo, outputs=resultado_subida
    )

    gr.Markdown("[← Volver a inicio](/inicio)")


with demo.route("Ver predicciones", "/ver_predicciones"):
    gr.Markdown("## Ver predicciones")
    gr.Markdown("🚧 Módulo en desarrollo. Próximamente disponible.")
    gr.Markdown("[← Volver a inicio](/inicio)")


with demo.route("Gráficos", "/graficos"):
    gr.Markdown("## Gráficos de tendencias semanales")
    gr.Markdown("🚧 Módulo en desarrollo. Próximamente disponible.")
    gr.Markdown("[← Volver a inicio](/inicio)")
