import gradio as gr


def saludar(nombre):
    return f"Hola, {nombre}"


demo = gr.Interface(
    fn=saludar,
    inputs=gr.Textbox(label="Tu nombre"),
    outputs=gr.Textbox(label="Respuesta"),
)
