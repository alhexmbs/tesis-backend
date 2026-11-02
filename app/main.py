import logging
from contextlib import asynccontextmanager

import gradio as gr
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount
from sqlalchemy import text

from app.core.config import settings
from app.core.seguridad import verificar_api_key
from app.database import Base, engine

# Importar los modelos registra sus tablas en Base.metadata: create_all solo crea las
# de los modelos importados aquí. Son las dos únicas tablas del sistema.
from app.models import historial, usuarios
from app.routers import auth as auth_router
from app.routers import prediccion as prediccion_router
from app.services.prediccion.servicio import cargar_artefactos
from app.ui.auth import autenticar
from app.ui.componentes import CSS_PATH, HEAD_ICONOS, TEMA, VENDOR_DIR, leer_js
from app.ui.paginas.inicio import demo as inicio_demo
from app.ui.paginas.login import demo as login_demo

logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

# create_all solo crea tablas nuevas: no agrega columnas a una tabla que ya existe.
# Las cuentas creadas antes de esta columna quedan en 0 y cambian su contraseña una
# vez en su próximo ingreso.
with engine.begin() as conexion:
    for sentencia in (
        "ALTER TABLE usuarios "
        "ADD COLUMN IF NOT EXISTS inicios_sesion INTEGER NOT NULL DEFAULT 0",
        # Recuperación de contraseña por correo. email queda en NULL: el
        # administrador lo carga por SQL a cada usuario.
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS email VARCHAR NULL",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS reset_token_hash VARCHAR NULL",
        "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS reset_token_expira TIMESTAMP NULL",
        # Único, pero varios usuarios pueden seguir sin correo (NULL no se repite).
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_usuarios_email ON usuarios (email)",
    ):
        conexion.execute(text(sentencia))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Carga los 3 modelos .joblib + config_servicio.json una sola vez al arrancar.
    cargar_artefactos()
    yield


app = FastAPI(
    title="API BENZIN AI",
    description="Backend for BENZIN AI",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # en producción poner la url de angular
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Toda la API REST exige el header X-API-Key (ver core/seguridad.py). Sin esto,
# cualquiera con el enlace podría crearse una cuenta, ver predicciones o sobrescribir
# el historial de ventas. La UI de Gradio no usa estas rutas y no se ve afectada.
app.include_router(auth_router.router, dependencies=[Depends(verificar_api_key)])
app.include_router(prediccion_router.router, dependencies=[Depends(verificar_api_key)])

# Copias locales de Bootstrap Icons y Flatpickr: la UI no depende de internet.
app.mount("/vendor", StaticFiles(directory=VENDOR_DIR), name="vendor")

# Fuerza modo claro al cargar, sin importar el tema del sistema/navegador.
FORCE_LIGHT_JS = leer_js("forzar_claro.js")

# En Gradio 6 el CSS y el tema ya no se pasan al constructor de Blocks (solo a
# launch(), que aquí nunca se llama): en apps montadas van en mount_gradio_app.
# "/login" queda fuera de auth: es la única página pública. No hay registro en la UI:
# las cuentas las crea el administrador con POST /api/auth/register.
app = gr.mount_gradio_app(
    app,
    login_demo,
    path="/login",
    js=FORCE_LIGHT_JS,
    css_paths=[CSS_PATH],
    theme=TEMA,
    head=HEAD_ICONOS,
)

# "/inicio" es un único Blocks con pestañas (predicción diaria, rango, carga de ventas,
# métricas): todas quedan detrás de la misma sesión de login.
if settings.ui_sin_login:
    logger.warning("UI_SIN_LOGIN activo: /inicio se abre sin autenticación.")

app = gr.mount_gradio_app(
    app,
    inicio_demo,
    path="/inicio",
    auth=None if settings.ui_sin_login else autenticar,
    js=FORCE_LIGHT_JS,
    css_paths=[CSS_PATH],
    theme=TEMA,
    head=HEAD_ICONOS,
)

# Sin sesión, Gradio mostraría en /inicio su propio formulario de login genérico (sin
# el diseño de /login). En su lugar, se redirige a /login. Se mira la misma cookie
# que usa Gradio: access-token-<cookie_id>, cuyo token debe seguir vivo en
# gradio_app.tokens (al cerrar sesión Gradio lo borra).
if not settings.ui_sin_login:
    _inicio_gradio = next(
        r.app for r in app.routes if isinstance(r, Mount) and r.path == "/inicio"
    )

    @app.middleware("http")
    async def redirigir_inicio_sin_sesion(request: Request, call_next):
        if request.method == "GET" and request.url.path in ("/inicio", "/inicio/"):
            cid = _inicio_gradio.cookie_id
            token = request.cookies.get(f"access-token-{cid}") or request.cookies.get(
                f"access-token-unsecure-{cid}"
            )
            if _inicio_gradio.tokens.get(token) is None:
                return RedirectResponse("/login/", status_code=302)
        return await call_next(request)


@app.get("/")
def health_check():
    from app.services.prediccion.servicio import obtener_artefactos

    art = obtener_artefactos()
    return {
        "message": "backend working",
        "modelos_cargados": art.productos,
        "modelo": art.config["modelo"],
    }
