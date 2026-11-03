import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.usuarios import Usuario
from app.utils.password import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.utils.validaciones import validar_datos_registro


def register_service(
    nombres, apellidos, dni, nro_celular, username, email, password, db: Session
):
    # Formato de los campos antes de tocar la base: DNI de 8 dígitos, celular de 9,
    # nombres sin números, correo válido. Lanza ErrorValidacion (subclase de
    # ValueError) al primer fallo. Devuelve los valores ya normalizados (sin espacios
    # sobrantes; el correo en minúsculas).
    datos = validar_datos_registro(nombres, apellidos, dni, nro_celular, username, email)
    nombres = datos["nombres"]
    apellidos = datos["apellidos"]
    dni = datos["dni"]
    nro_celular = datos["nro_celular"]
    username = datos["username"]
    email = datos["email"]

    # verificar si no existe un usuario con el mismo username
    stmt_username = select(Usuario).where(Usuario.username == username)
    user_db_by_username = db.scalar(stmt_username)
    username_duplicated_code = 1
    if user_db_by_username:
        return username_duplicated_code

    # verificar si no existe un usuario con el mismo dni
    stmt_dni = select(Usuario).where(Usuario.dni == dni)
    user_db_by_dni = db.scalar(stmt_dni)
    dni_duplicated_code = 2
    if user_db_by_dni:
        return dni_duplicated_code

    # verificar si no existe un usuario con el mismo nro_celular
    stmt_nro_celular = select(Usuario).where(Usuario.nro_celular == nro_celular)
    user_db_by_nro_celular = db.scalar(stmt_nro_celular)
    nro_celular_duplicated_code = 3
    if user_db_by_nro_celular:
        return nro_celular_duplicated_code

    # verificar si no existe un usuario con el mismo email (sin distinguir
    # mayúsculas: los correos cargados antes por SQL pueden tenerlas)
    stmt_email = select(Usuario).where(func.lower(Usuario.email) == email)
    user_db_by_email = db.scalar(stmt_email)
    email_duplicated_code = 4
    if user_db_by_email:
        return email_duplicated_code

    # Agrupar datos personales para evitar que se usen en la contraseña
    # Convertimos todo a string por seguridad para zxcvbn
    user_data = [
        str(nombres),
        str(apellidos),
        str(dni),
        str(nro_celular),
        str(username),
        str(email),
    ]

    # Validar la fortaleza. Si falla, lanzará el ValueError automáticamente.
    validate_password_strength(password, user_data=user_data)

    # Hashear la contraseña validada
    hashed_password = hash_password(password)

    # Crear el usuario
    nuevo_usuario = Usuario(
        nombres=nombres,
        apellidos=apellidos,
        dni=dni,
        nro_celular=nro_celular,
        username=username,
        email=email,
        password=hashed_password,
    )

    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)

    return nuevo_usuario


def login_service(username, password, db: Session):
    stmt_user = select(Usuario).where(Usuario.username == username)
    user = db.scalar(stmt_user)

    if not user or not verify_password(password, user.password):
        return None

    return user


def registrar_inicio_sesion(user: Usuario, db: Session):
    # Se suma en la base (inicios_sesion + 1) y no en Python, así dos ingresos a la
    # vez del mismo usuario no se pisan el contador.
    user.inicios_sesion = Usuario.inicios_sesion + 1
    db.commit()


def cambiar_password_service(user: Usuario, nueva_password, db: Session):
    if verify_password(nueva_password, user.password):
        raise ValueError("La nueva contraseña debe ser distinta de la actual.")

    # Mismas reglas que al registrar: no puede contener sus datos personales.
    user_data = [
        str(user.nombres),
        str(user.apellidos),
        str(user.dni),
        str(user.nro_celular),
        str(user.username),
    ]
    validate_password_strength(nueva_password, user_data=user_data)

    user.password = hash_password(nueva_password)
    # Cambiar la contraseña exige usuario y contraseña correctos: cuenta como su
    # primer inicio de sesión, y así el siguiente ingreso ya no pide cambiarla.
    user.inicios_sesion = Usuario.inicios_sesion + 1
    db.commit()


# --------------------------------------------------------------------------- #
# Recuperación de contraseña por correo
# --------------------------------------------------------------------------- #
VIGENCIA_TOKEN_MIN = 30
# Entre dos pedidos de recuperación de la misma cuenta: evita llenar su bandeja.
ESPERA_REENVIO = timedelta(minutes=1)


def _ahora_utc() -> datetime:
    # La columna es TIMESTAMP sin zona: se guarda UTC "sin zona" y se compara igual.
    return datetime.now(UTC).replace(tzinfo=None)


def _hash_token(token: str) -> str:
    # En la base solo queda el hash: quien lea la tabla no puede usar el enlace.
    return hashlib.sha256(token.encode()).hexdigest()


def usuario_por_email(email: str, db: Session):
    # Sin distinguir mayúsculas: el correo pudo cargarse por SQL como "Ana@Mail.com".
    stmt = select(Usuario).where(
        func.lower(Usuario.email) == email.lower(), Usuario.estado.is_(True)
    )
    return db.scalar(stmt)


def crear_token_recuperacion(user: Usuario, db: Session) -> str | None:
    """Genera el token del enlace y guarda su hash con vencimiento.

    Devuelve None si ya se envió un enlace hace menos de ESPERA_REENVIO. Un enlace
    nuevo invalida al anterior (se reemplaza el hash).
    """
    ahora = _ahora_utc()
    if user.reset_token_expira is not None:
        enviado = user.reset_token_expira - timedelta(minutes=VIGENCIA_TOKEN_MIN)
        if ahora - enviado < ESPERA_REENVIO:
            return None

    token = secrets.token_urlsafe(32)
    user.reset_token_hash = _hash_token(token)
    user.reset_token_expira = ahora + timedelta(minutes=VIGENCIA_TOKEN_MIN)
    db.commit()
    return token


def usuario_por_token(token: str, db: Session):
    """Usuario dueño de un token vigente; None si no existe o ya venció."""
    if not token:
        return None
    stmt = select(Usuario).where(
        Usuario.reset_token_hash == _hash_token(token), Usuario.estado.is_(True)
    )
    user = db.scalar(stmt)
    if user is None or user.reset_token_expira is None:
        return None
    if user.reset_token_expira < _ahora_utc():
        return None
    return user


def restablecer_password_service(user: Usuario, nueva_password, db: Session):
    """Cambia la contraseña con un token válido y deja el enlace inservible."""
    # Se borra el token y se cambia la contraseña en un mismo commit (el de
    # cambiar_password_service). Mismas reglas que el primer ingreso: si la nueva
    # no sirve, lanza ValueError antes del commit y el enlace sigue sirviendo.
    user.reset_token_hash = None
    user.reset_token_expira = None
    cambiar_password_service(user, nueva_password, db)


def registrar_accion(username: str, texto: str, db: Session) -> None:
    """Guarda en ``usuarios.accion`` lo último que hizo el usuario (sobrescribe)."""
    user = db.scalar(select(Usuario).where(Usuario.username == username))
    if user is None:
        return
    user.accion = texto
    db.commit()
