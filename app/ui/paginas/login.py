import gradio as gr

from app.ui.componentes import leer_js

LOGIN_JS = leer_js("login.js")

with gr.Blocks(title="Iniciar sesión") as demo:
    gr.Markdown("## Iniciar sesión")

    username = gr.Textbox(label="Usuario")
    password = gr.Textbox(label="Contraseña", type="password")
    login_error = gr.HTML()

    boton = gr.Button("Iniciar sesión", variant="primary")

    gr.Markdown("¿No tienes cuenta? [Regístrate aquí](/registro)")

    boton.click(
        fn=None,
        inputs=[username, password],
        outputs=login_error,
        js=LOGIN_JS,
    )
