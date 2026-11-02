import gradio as gr

from app.services.correo import CorreoNoEnviado
from app.ui.auth import (
    cambiar_password,
    estado_login,
    restablecer_password,
    solicitar_recuperacion,
    token_valido,
)
from app.ui.componentes import banner, cabecera_tarjeta, error_html, leer_js

LOGIN_JS = leer_js("login.js")

# Qué formulario se ve en la tarjeta. Solo uno a la vez.
FORMULARIOS = ("login", "cambio", "olvido", "reset")


def _mostrar(cual: str) -> tuple:
    """Visibilidad de los 4 formularios, en el orden de FORMULARIOS."""
    return tuple(gr.update(visible=(f == cual)) for f in FORMULARIOS)


def verificar_ui(username: str, password: str):
    """Primer paso del botón "Iniciar sesión": revisa las credenciales en Python.

    Devuelve (mensaje, acción, formulario de login, formulario de cambio). Si la
    acción es "ok", el paso siguiente (login.js) abre la sesión; si es "cambiar"
    (nunca entró antes), se muestra el formulario de cambio de contraseña.
    """
    if not username or not password:
        return error_html("Ingresa usuario y contraseña."), "error", gr.update(), gr.update()

    estado = estado_login(username, password)
    if estado == "cambiar":
        return "", "cambiar", gr.update(visible=False), gr.update(visible=True)
    if estado == "error":
        # Mismo mensaje para clave errada y usuario bloqueado (ui/auth.py): así no se
        # revela qué usuarios existen.
        return error_html("Usuario o contraseña incorrectos."), "error", gr.update(), gr.update()
    return "", "ok", gr.update(), gr.update()


def _listo_para_entrar() -> str:
    return banner(
        "ok",
        "check-circle",
        "Contraseña actualizada",
        '<div class="msg-cuerpo">Inicia sesión con tu nueva contraseña.</div>',
    )


def cambiar_ui(username: str, password: str, nueva: str, confirmar: str):
    """Guarda la contraseña nueva y vuelve al login para entrar con ella."""
    sin_cambios = (gr.update(),) * 6
    if not nueva or not confirmar:
        return (error_html("Completa los dos campos."), *sin_cambios)
    if nueva != confirmar:
        return (error_html("Las contraseñas no coinciden."), *sin_cambios)

    try:
        cambiar_password(username, password, nueva)
    except ValueError as e:
        return (error_html("No se pudo cambiar la contraseña", str(e)), *sin_cambios)

    return (
        "",  # mensaje del formulario de cambio
        _listo_para_entrar(),  # mensaje del login
        gr.update(value=""),  # contraseña vieja fuera del campo
        gr.update(visible=True),  # formulario de login
        gr.update(visible=False),  # formulario de cambio
        gr.update(value=""),
        gr.update(value=""),
    )


# --------------------------------------------------------------------------- #
# Olvidé mi contraseña
# --------------------------------------------------------------------------- #
def enviar_enlace_ui(email: str):
    """Pide el enlace de recuperación. El mensaje es el mismo exista o no el correo."""
    if not email or "@" not in email:
        return error_html("Ingresa un correo válido.")
    try:
        solicitar_recuperacion(email)
    except CorreoNoEnviado:
        return error_html(
            "No se pudo enviar el correo",
            "Intenta más tarde o comunícate con el administrador del sistema.",
        )
    return banner(
        "ok",
        "envelope-check",
        "Revisa tu correo",
        '<div class="msg-cuerpo">Te enviamos un enlace '
        "para cambiar tu contraseña. Vence en 30 minutos. Revisa también la sessión "
        "de spam.</div>",
    )


def cargar_token(request: gr.Request):
    """Al abrir /login/?token=...: si el enlace del correo es válido, muestra el
    formulario de nueva contraseña; si venció, lo avisa sobre el login."""
    token = request.query_params.get("token", "") if request else ""
    if not token:
        return "", "", *_mostrar("login")
    if token_valido(token):
        return token, "", *_mostrar("reset")
    aviso = error_html(
        "El enlace venció o ya fue usado",
        "Pide uno nuevo con «¿Olvidaste tu contraseña?».",
    )
    return "", aviso, *_mostrar("login")


def restablecer_ui(token: str, nueva: str, confirmar: str):
    """Guarda la contraseña nueva del enlace del correo y vuelve al login."""
    sin_cambios = (gr.update(),) * (2 + len(FORMULARIOS))
    if not nueva or not confirmar:
        return (error_html("Completa los dos campos."), *sin_cambios)
    if nueva != confirmar:
        return (error_html("Las contraseñas no coinciden."), *sin_cambios)
    try:
        restablecer_password(token, nueva)
    except ValueError as e:
        return (error_html("No se pudo cambiar la contraseña", str(e)), *sin_cambios)
    return ("", "", _listo_para_entrar(), *_mostrar("login"))


with gr.Blocks(title="Iniciar sesión") as demo:
    # `tarjeta` (estilos.css) centra el formulario en un recuadro angosto.
    with gr.Column(elem_classes="tarjeta"):
        gr.HTML(cabecera_tarjeta("Inicia sesión para continuar"))

        with gr.Column() as form_login:
            username = gr.Textbox(label="Usuario", placeholder="Ingrese el nombre de usuario")
            password = gr.Textbox(
                label="Contraseña", type="password", placeholder="Ingrese la contraseña"
            )
            login_error = gr.HTML()

            boton = gr.Button("Iniciar sesión", variant="primary", size="lg")
            boton_olvido = gr.Button(
                "¿Olvidaste tu contraseña?", variant="secondary", size="sm"
            )

        # Primer ingreso (inicios_sesion == 0): cambio obligatorio de contraseña.
        with gr.Column(visible=False) as form_cambio:
            gr.HTML(
                banner(
                    "info",
                    "shield-lock",
                    "Es tu primer ingreso",
                    '<div class="msg-cuerpo">Por seguridad, cambia la contraseña que '
                    "te dio el administrador.</div>",
                )
            )
            nueva = gr.Textbox(label="Nueva contraseña", type="password")
            confirmar = gr.Textbox(label="Repite la nueva contraseña", type="password")
            cambio_error = gr.HTML()
            boton_cambio = gr.Button("Cambiar contraseña", variant="primary", size="lg")

        # "¿Olvidaste tu contraseña?": se pide el correo para enviar el enlace.
        with gr.Column(visible=False) as form_olvido:
            gr.HTML(
                banner(
                    "info",
                    "envelope",
                    "Recupera tu contraseña",
                    '<div class="msg-cuerpo">Ingresa el correo registrado en tu cuenta '
                    "y te enviaremos un enlace para cambiarla.</div>",
                )
            )
            olvido_email = gr.Textbox(label="Correo", placeholder="nombre@correo.com")
            olvido_msg = gr.HTML()
            boton_enviar = gr.Button("Enviar enlace", variant="primary", size="lg")
            boton_volver = gr.Button("Volver al inicio de sesión", variant="secondary", size="sm")

        # Se llega desde el enlace del correo (/login/?token=...).
        with gr.Column(visible=False) as form_reset:
            gr.HTML(
                banner(
                    "info",
                    "shield-lock",
                    "Crea tu nueva contraseña",
                    '<div class="msg-cuerpo">Elige una contraseña que no hayas usado '
                    "antes en este sistema.</div>",
                )
            )
            reset_nueva = gr.Textbox(label="Nueva contraseña", type="password")
            reset_confirmar = gr.Textbox(
                label="Repite la nueva contraseña", type="password"
            )
            reset_error = gr.HTML()
            boton_reset = gr.Button("Guardar contraseña", variant="primary", size="lg")

        # Resultado de verificar_ui que lee login.js. "hidden" y no visible=False:
        # el componente tiene que existir en la página para que el JS reciba su valor.
        accion = gr.Textbox(visible="hidden")
        # Token del enlace del correo. Vive en el servidor, no se muestra.
        token = gr.State("")

    formularios = [form_login, form_cambio, form_olvido, form_reset]

    (
        boton.click(
            verificar_ui,
            inputs=[username, password],
            outputs=[login_error, accion, form_login, form_cambio],
        ).then(
            fn=None,
            inputs=[username, password, accion, login_error],
            outputs=login_error,
            js=LOGIN_JS,
        )
    )

    boton_cambio.click(
        cambiar_ui,
        inputs=[username, password, nueva, confirmar],
        outputs=[
            cambio_error,
            login_error,
            password,
            form_login,
            form_cambio,
            nueva,
            confirmar,
        ],
    )

    boton_olvido.click(
        lambda: ("", *_mostrar("olvido")), outputs=[olvido_msg, *formularios]
    )
    boton_volver.click(lambda: _mostrar("login"), outputs=formularios)
    boton_enviar.click(enviar_enlace_ui, inputs=olvido_email, outputs=olvido_msg)

    boton_reset.click(
        restablecer_ui,
        inputs=[token, reset_nueva, reset_confirmar],
        outputs=[reset_error, token, login_error, *formularios],
    )

    demo.load(cargar_token, outputs=[token, login_error, *formularios])
