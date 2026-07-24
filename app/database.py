from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url)

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