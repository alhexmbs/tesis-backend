import gradio as gr

from app.database import SessionLocal
from app.services.auth import register_service
from app.ui.componentes import banner, cabecera_tarjeta, enlace_tarjeta
from app.utils.validaciones import LARGO_CELULAR, LARGO_DNI, ErrorValidacion

SIN_ERROR = gr.update(value="", visible=False)

# Orden de los HTML de error en `outputs`. `_salida` enciende solo el que toca.
CAMPOS = ["nombres", "apellidos", "dni", "nro_celular", "username", "password"]

# Filtros que corren en el navegador en cada tecla (y en cada pegado): borran lo que
# el campo no admite antes de que llegue al servidor. Son comodidad, no seguridad:
# la validación real está en `app.utils.validaciones`, que corre en el backend.
SOLO_LETRAS_JS = "(v) => (v || '').replace(/[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]/g, '')"
SOLO_DIGITOS_JS = r"(v) => (v || '').replace(/\D/g, '').slice(0, %d)"


def error_en(mensaje):
    return gr.update(value=banner("err", "exclamation-triangle", mensaje), visible=True)


def _salida(campo: str | None = None, mensaje: str = "", resultado: str = ""):
    """Un mensaje bajo el campo indicado, el resto de los avisos apagados."""
    errores = [error_en(mensaje) if c == campo else SIN_ERROR for c in CAMPOS]
    return (*errores, resultado)


def registrar(nombres, apellidos, dni, nro_celular, username, password):
    db = SessionLocal()
    try:
        resultado = register_service(
            nombres, apellidos, dni, nro_celular, username, password, db
        )
    except ErrorValidacion as e:
        # Formato del campo: el propio error sabe bajo cuál se pinta.
        return _salida(e.campo, str(e))
    except ValueError as e:
        # Lo que queda son los avisos de fortaleza de zxcvbn.
        return _salida("password", str(e))
    finally:
        db.close()

    if resultado == 1:
        return _salida(
            "username", "El nombre de usuario ya ha sido registrado, intente con otro."
        )
    if resultado == 2:
        return _salida("dni", "El DNI ya ha sido registrado.")
    if resultado == 3:
        return _salida("nro_celular", "El número de celular ya ha sido registrado.")

    return _salida(
        resultado=banner(
            "ok",
            "check-circle",
            "Usuario registrado correctamente. Ya puedes iniciar sesión.",
        )
    )


with gr.Blocks(title="Registro de usuario") as demo:
    with gr.Column(elem_classes=["tarjeta", "tarjeta-ancha"]):
        gr.HTML(cabecera_tarjeta("Crea tu cuenta"))

        nombres = gr.Textbox(label="Nombres", max_length=60)
        nombre_error = gr.HTML(visible=False)

        apellidos = gr.Textbox(label="Apellidos", max_length=60)
        apellido_error = gr.HTML(visible=False)

        dni = gr.Textbox(label=f"DNI ({LARGO_DNI} dígitos)", max_length=LARGO_DNI)
        dni_error = gr.HTML(visible=False)

        nro_celular = gr.Textbox(
            label=f"Número de celular ({LARGO_CELULAR} dígitos)",
            max_length=LARGO_CELULAR,
        )
        nro_celular_error = gr.HTML(visible=False)

        username = gr.Textbox(label="Usuario", max_length=30)
        username_error = gr.HTML(visible=False)

        password = gr.Textbox(label="Contraseña", type="password")
        password_error = gr.HTML(visible=False)

        boton = gr.Button("Registrar", variant="primary", size="lg")
        resultado = gr.HTML()

        gr.HTML(enlace_tarjeta("¿Ya tienes una cuenta?", "Inicia sesión", "/login"))

    nombres.input(fn=None, inputs=nombres, outputs=nombres, js=SOLO_LETRAS_JS)
    apellidos.input(fn=None, inputs=apellidos, outputs=apellidos, js=SOLO_LETRAS_JS)
    dni.input(fn=None, inputs=dni, outputs=dni, js=SOLO_DIGITOS_JS % LARGO_DNI)
    nro_celular.input(
        fn=None,
        inputs=nro_celular,
        outputs=nro_celular,
        js=SOLO_DIGITOS_JS % LARGO_CELULAR,
    )

    boton.click(
        fn=registrar,
        inputs=[nombres, apellidos, dni, nro_celular, username, password],
        outputs=[
            nombre_error,
            apellido_error,
            dni_error,
            nro_celular_error,
            username_error,
            password_error,
            resultado,
        ],
    )
