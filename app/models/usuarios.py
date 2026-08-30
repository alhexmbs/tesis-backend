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
