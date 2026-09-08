from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.usuarios import Usuario
from app.utils.password import (
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.utils.validaciones import validar_datos_registro


def register_service(
    nombres, apellidos, dni, nro_celular, username, password, db: Session
):
    # Formato de los campos antes de tocar la base: DNI de 8 dígitos, celular de 9,
    # nombres sin números. Lanza ErrorValidacion (subclase de ValueError) al primer
    # fallo. Devuelve los valores ya normalizados (sin espacios sobrantes).
    datos = validar_datos_registro(nombres, apellidos, dni, nro_celular, username)
    nombres = datos["nombres"]
    apellidos = datos["apellidos"]
    dni = datos["dni"]
    nro_celular = datos["nro_celular"]
    username = datos["username"]

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
