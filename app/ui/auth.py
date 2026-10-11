import threading
import time

from app.database import SessionLocal
from app.services.auth import login_service

# Bloqueo por fuerza bruta: tras MAX_INTENTOS fallos seguidos con un mismo usuario,
# ese usuario queda bloqueado BLOQUEO_SEGUNDOS aunque luego ponga la contraseña bien.
# Es por usuario y no por IP porque Gradio solo le pasa a `autenticar` el usuario y la
# contraseña. Vive en memoria: basta con un solo proceso (así corre en Railway) y se
# limpia al reiniciar el servidor, lo cual sirve también para desbloquear a mano.
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 15 * 60

# usuario -> (fallos seguidos, momento del último fallo)
_fallos: dict[str, tuple[int, float]] = {}
# Gradio atiende cada login en un hilo distinto: el lock evita que dos intentos a la
# vez lean y escriban el contador al mismo tiempo.
_lock = threading.Lock()


def _bloqueado(username: str, ahora: float) -> bool:
    fallos, ultimo = _fallos.get(username, (0, 0.0))
    return fallos >= MAX_INTENTOS and ahora - ultimo < BLOQUEO_SEGUNDOS


def _registrar_fallo(username: str, ahora: float) -> None:
    fallos, ultimo = _fallos.get(username, (0, 0.0))
    # Si el bloqueo anterior ya venció, se empieza a contar de nuevo.
    if ahora - ultimo >= BLOQUEO_SEGUNDOS:
        fallos = 0
    _fallos[username] = (fallos + 1, ahora)

    # Se borran los vencidos para que probar miles de usuarios inventados no haga
    # crecer el diccionario sin límite.
    for u in [u for u, (_, t) in _fallos.items() if ahora - t >= BLOQUEO_SEGUNDOS]:
        del _fallos[u]


def autenticar(username: str, password: str) -> bool:
    username = (username or "").strip()
    ahora = time.monotonic()

    with _lock:
        if _bloqueado(username, ahora):
            # Ni se consulta la base: durante el bloqueo no se puede seguir probando.
            return False

    db = SessionLocal()
    try:
        ok = login_service(username, password, db) is not None
    finally:
        db.close()

    with _lock:
        if ok:
            _fallos.pop(username, None)
        else:
            _registrar_fallo(username, ahora)
    return ok
