from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)

    nombres = Column(String, nullable=False, index=False)
    apellidos = Column(String, nullable=False, index=False)
    dni = Column(String, nullable=False, unique=True, index=False)
    nro_celular = Column(String, nullable=False, unique=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True)
    password = Column(String, nullable=False, index=False)

    fecha_creacion = Column(DateTime, default=lambda: datetime.now(UTC))
    estado = Column(Boolean, default=True, nullable=False, index=True)

    # Veces que el usuario se autenticó. En 0 = nunca entró: tiene que cambiar la
    # contraseña que le dio el administrador antes de poder usar el sistema.
    inicios_sesion = Column(Integer, default=0, server_default="0", nullable=False)

    # Correo para recuperar la contraseña. Opcional: lo carga el administrador por SQL.
    email = Column(String, nullable=True, unique=True, index=True)

    # Recuperación de contraseña: se guarda el HASH del enlace enviado por correo
    # (nunca el enlace en sí) y hasta cuándo vale, en hora UTC. Se borran al usarlo.
    reset_token_hash = Column(String, nullable=True)
    reset_token_expira = Column(DateTime, nullable=True)
