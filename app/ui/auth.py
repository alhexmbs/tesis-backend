import threading
import time

import logging
from urllib.parse import urlsplit

from app.core.config import settings
from app.database import SessionLocal
from app.models.usuarios import Usuario
from app.services.auth import (
    VIGENCIA_TOKEN_MIN,
    cambiar_password_service,
    crear_token_recuperacion,
    login_service,
    registrar_inicio_sesion,
    restablecer_password_service,
    usuario_por_email,
    usuario_por_token,
)
from app.services.correo import CorreoNoEnviado, enviar_correo_recuperacion

logger = logging.getLogger(__name__)

# Bloqueo por fuerza bruta: tras MAX_INTENTOS fallos seguidos con un mismo usuario,
# ese usuario queda bloqueado BLOQUEO_SEGUNDOS aunque luego ponga la contraseña bien.
# Es por usuario y no por IP porque Gradio solo le pasa a `autenticar` el usuario y la
# contraseña. Vive en memoria: basta con un solo proceso (así corre en Railway) y se
# limpia al reiniciar el servidor, lo cual sirve también para desbloquear a mano.
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 15 * 60

# usuario -> (fallos seguidos, momento del último fallo)
_fallos: dict[str, tuple[int, float]] = {}
# Gradio atiende cada login en un hilo distinto: el lock evita que dos intentos a la
# vez lean y escriban el contador al mismo tiempo.
_lock = threading.Lock()


def _bloqueado(username: str, ahora: float) -> bool:
    fallos, ultimo = _fallos.get(username, (0, 0.0))
    return fallos >= MAX_INTENTOS and ahora - ultimo < BLOQUEO_SEGUNDOS


def _registrar_fallo(username: str, ahora: float) -> None:
    fallos, ultimo = _fallos.get(username, (0, 0.0))
    # Si el bloqueo anterior ya venció, se empieza a contar de nuevo.
    if ahora - ultimo >= BLOQUEO_SEGUNDOS:
        fallos = 0
    _fallos[username] = (fallos + 1, ahora)

    # Se borran los vencidos para que probar miles de usuarios inventados no haga
    # crecer el diccionario sin límite.
    for u in [u for u, (_, t) in _fallos.items() if ahora - t >= BLOQUEO_SEGUNDOS]:
        del _fallos[u]


def _verificar(username: str, password: str, db) -> Usuario | None:
    """Usuario si la contraseña es correcta; None si no o si está bloqueado.

    Toda verificación de contraseña de la UI pasa por aquí, así el bloqueo por
    fuerza bruta cubre también el formulario de cambio de contraseña.
    """
    username = (username or "").strip()
    ahora = time.monotonic()

    with _lock:
        if _bloqueado(username, ahora):
            # Ni se consulta la base: durante el bloqueo no se puede seguir probando.
            return None

    user = login_service(username, password, db)

    with _lock:
        if user is not None:
            _fallos.pop(username, None)
        else:
            _registrar_fallo(username, ahora)
    return user


def autenticar(username: str, password: str) -> bool:
    """La usa Gradio en POST /inicio/login para abrir la sesión."""
    db = SessionLocal()
    try:
        user = _verificar(username, password, db)
        # Primer ingreso: no se abre la sesión hasta cambiar la contraseña. Se corta
        # aquí y no solo en la página de login, porque /inicio/login se puede llamar
        # directo y saltarse el formulario.
        if user is None or user.inicios_sesion == 0:
            return False
        registrar_inicio_sesion(user, db)
        return True
    finally:
        db.close()


def estado_login(username: str, password: str) -> str:
    """"ok" (puede entrar), "cambiar" (primer ingreso) o "error"."""
    db = SessionLocal()
    try:
        user = _verificar(username, password, db)
        if user is None:
            return "error"
        return "cambiar" if user.inicios_sesion == 0 else "ok"
    finally:
        db.close()


def cambiar_password(username: str, password_actual: str, nueva: str) -> None:
    """Cambio obligatorio del primer ingreso. Lanza ValueError con el motivo."""
    db = SessionLocal()
    try:
        user = _verificar(username, password_actual, db)
        # Solo para el primer ingreso: quien ya entró antes no tiene por qué llegar
        # a este formulario.
        if user is None or user.inicios_sesion != 0:
            raise ValueError("Usuario o contraseña incorrectos.")
        cambiar_password_service(user, nueva, db)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Recuperación de contraseña por correo
# --------------------------------------------------------------------------- #
def solicitar_recuperacion(email: str) -> None:
    """Envía el enlace de recuperación si el correo pertenece a una cuenta activa.

    No dice si el correo existe: la pantalla muestra siempre el mismo mensaje, así
    nadie puede averiguar qué correos están registrados. Solo lanza CorreoNoEnviado
    si el envío no está configurado o Resend falla.
    """
    if not settings.resend_api_key:
        raise CorreoNoEnviado("Falta configurar RESEND_API_KEY.")

    email = (email or "").strip().lower()
    db = SessionLocal()
    try:
        user = usuario_por_email(email, db)
        if user is None:
            logger.info("Recuperación pedida para un correo no registrado.")
            return
        token = crear_token_recuperacion(user, db)
        if token is None:
            return  # ya se envió uno hace menos de un minuto
        # Solo esquema + dominio de URL_PUBLICA: si alguien la configura con una ruta
        # (".../login"), el enlace quedaría /login/login/ y Gradio responde 405.
        base = urlsplit(settings.url_publica)
        enlace = f"{base.scheme}://{base.netloc}/login/?token={token}"
        enviar_correo_recuperacion(user.email, user.nombres, enlace, VIGENCIA_TOKEN_MIN)
    finally:
        db.close()


def token_valido(token: str) -> bool:
    db = SessionLocal()
    try:
        return usuario_por_token(token, db) is not None
    finally:
        db.close()


def restablecer_password(token: str, nueva: str) -> None:
    """Cambia la contraseña con el enlace del correo. Lanza ValueError con el motivo."""
    db = SessionLocal()
    try:
        user = usuario_por_token(token, db)
        if user is None:
            raise ValueError("El enlace venció o ya fue usado. Pide uno nuevo.")
        username = user.username
        restablecer_password_service(user, nueva, db)
    finally:
        db.close()
    # Si la cuenta estaba bloqueada por intentos fallidos, queda libre: el usuario
    # acaba de demostrar que es el dueño del correo.
    with _lock:
        _fallos.pop(username, None)
