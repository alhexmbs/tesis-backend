from app.database import SessionLocal
from app.services.auth import login_service


def autenticar(username: str, password: str) -> bool:
    db = SessionLocal()
    try:
        return login_service(username, password, db) is not None
    finally:
        db.close()
