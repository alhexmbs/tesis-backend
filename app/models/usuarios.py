from app.database import Base
from sqlalchemy import Column, DateTime, Integer, Boolean, String
from datetime import UTC, datetime

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)

    nombres = Column(String, nullable=False, index=False)
    apellidos = Column(String, nullable=False, index=False)
    username = Column(String, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    hashed_password = Column(String, nullable=False, index=False)

    fecha_creacion = Column(DateTime, default=lambda: datetime.now(UTC))
    estado = Column(Boolean, default=True, nullable=False, index=True)