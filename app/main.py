from contextlib import asynccontextmanager

import gradio as gr
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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

Base.metadata.create_all(bind=engine)


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
app = gr.mount_gradio_app(
    app,
    inicio_demo,
    path="/inicio",
    auth=autenticar,
    js=FORCE_LIGHT_JS,
    css_paths=[CSS_PATH],
    theme=TEMA,
    head=HEAD_ICONOS,
)


@app.get("/")
def health_check():
    from app.services.prediccion.servicio import obtener_artefactos

    art = obtener_artefactos()
    return {
        "message": "backend working",
        "modelos_cargados": art.productos,
        "modelo": art.config["modelo"],
    }
