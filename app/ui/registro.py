import gradio as gr

from app.database import SessionLocal
from app.services.auth import register_service


SIN_ERROR = gr.update(value="", visible=False)


def error_en(mensaje):
    return gr.update(value=f"❌ {mensaje}", visible=True)


def registrar(nombres, apellidos, dni, nro_celular, username, password):
    db = SessionLocal()
    try:
        resultado = register_service(
            nombres, apellidos, dni, nro_celular, username, password, db
        )
    except ValueError as e:
        return SIN_ERROR, SIN_ERROR, SIN_ERROR, error_en(str(e)), ""
    finally:
        db.close()

    if resultado == 1:
        return (
            error_en("El nombre de usuario ya ha sido registrado, intente con otro."),
            SIN_ERROR,
            SIN_ERROR,
            SIN_ERROR,
            "",
        )
    if resultado == 2:
        return (
            SIN_ERROR,
            error_en("El DNI ya ha sido registrado."),
            SIN_ERROR,
            SIN_ERROR,
            "",
        )
    if resultado == 3:
        return (
            SIN_ERROR,
            SIN_ERROR,
            error_en("El número de celular ya ha sido registrado."),
            SIN_ERROR,
            "",
        )

    return (
        SIN_ERROR,
        SIN_ERROR,
        SIN_ERROR,
        SIN_ERROR,
        "Usuario registrado correctamente. Ya puedes iniciar sesión.",
    )


with gr.Blocks(title="Registro de usuario") as demo:
    gr.Markdown("## Registro de usuario")
    gr.Markdown("¿Ya tienes una cuenta? [Inicia sesión aquí](/login)")

    nombres = gr.Textbox(label="Nombres")
    nombre_error = gr.Markdown(visible=False)

    apellidos = gr.Textbox(label="Apellidos")
    apellido_error = gr.Markdown(visible=False)

    dni = gr.Textbox(label="DNI")
    dni_error = gr.Markdown(visible=False)

    nro_celular = gr.Textbox(label="Número de celular")
    nro_celular_error = gr.Markdown(visible=False)

    username = gr.Textbox(label="Usuario")
    username_error = gr.Markdown(visible=False)

    password = gr.Textbox(label="Contraseña", type="password")
    password_error = gr.Markdown(visible=False)

    boton = gr.Button("Registrar", variant="primary")
    resultado = gr.Markdown()

    boton.click(
        fn=registrar,
        inputs=[nombres, apellidos, dni, nro_celular, username, password],
        outputs=[
            username_error,
            dni_error,
            nro_celular_error,
            password_error,
            resultado,
        ],
    )
