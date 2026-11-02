from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# Railway corta las conexiones que quedan inactivas un rato. Sin esto, el pool
# entrega una conexión ya cerrada y la consulta falla con
# "SSL error: unexpected eof while reading".
# - pool_pre_ping: antes de usar una conexión, la prueba; si murió, abre otra.
# - pool_recycle: renueva cada conexión a los 5 minutos, antes de que la corten.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
)

# fábrica de sesiones -> cada vez que alguien hace una petición, se abre una sesión
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# base para los modelos -> Las tablas heredarán de aquí
Base = declarative_base()


# dependencia para FastAPI - abre la conexión al recibir petición y la cierra al terminar
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
