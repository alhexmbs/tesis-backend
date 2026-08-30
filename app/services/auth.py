from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.usuarios import Usuario
from app.utils.password import (
    hash_password,
    validate_password_strength,
    verify_password,
)


def register_service(
    nombres, apellidos, dni, nro_celular, username, password, db: Session
):
    # Agrupar datos personales para evitar que se usen en la contraseña
    # Convertimos todo a string por seguridad para zxcvbn
    user_data = [
        str(nombres),
        str(apellidos),
        str(dni),
        str(nro_celular),
        str(username),
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
