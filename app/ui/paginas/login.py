import gradio as gr

from app.ui.componentes import cabecera_tarjeta, leer_js

LOGIN_JS = leer_js("login.js")

with gr.Blocks(title="Iniciar sesión") as demo:
    # `tarjeta` (estilos.css) centra el formulario en un recuadro angosto.
    with gr.Column(elem_classes="tarjeta"):
        gr.HTML(cabecera_tarjeta("Inicia sesión para continuar"))

        username = gr.Textbox(label="Usuario", placeholder="Tu usuario")
        password = gr.Textbox(
            label="Contraseña", type="password", placeholder="Tu contraseña"
        )
        login_error = gr.HTML()

        boton = gr.Button("Iniciar sesión", variant="primary", size="lg")

    boton.click(
        fn=None,
        inputs=[username, password],
        outputs=login_error,
        js=LOGIN_JS,
    )
