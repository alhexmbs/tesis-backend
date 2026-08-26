from app.utils.password import validate_password_strength, hash_password, verify_password
from app.models.usuarios import Usuario
from sqlalchemy.orm import Session
from sqlalchemy import select

def register_service(
        nombres,
        apellidos,
        email,
        username,
        user_password,
        db: Session
    ):

    #validate_password_strength()

    hashed = hash_password(user_password)

    nuevo_usuario = Usuario(
        nombres = nombres,
        apellidos = apellidos,
        username = username,
        email = email,
        hashed_password = hashed
    )

    db.add(nuevo_usuario)
    db.commit()
    db.refresh(nuevo_usuario)

    return nuevo_usuario

def login_service(
        username,
        user_password,
        db: Session
    ):

    stmt_user = select(Usuario).where(Usuario.username == username)
    user = db.scalar(stmt_user)

    if not user or not verify_password(user_password, user.hashed_password):
        return None
    return user