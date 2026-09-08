from contextlib import asynccontextmanager

import gradio as gr
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine

# Importar los modelos registra sus tablas en Base.metadata: create_all solo crea las
# de los modelos importados aquí. Son las dos únicas tablas del sistema.
from app.models import historial, usuarios
from app.routers import auth as auth_router
from app.routers import prediccion as prediccion_router
from app.services.prediccion.servicio import cargar_artefactos
from app.ui.auth import autenticar
from app.ui.estilos import CSS
from app.ui.inicio import demo as inicio_demo
from app.ui.login import demo as login_demo
from app.ui.registro import demo as registro_demo

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

app.include_router(auth_router.router)
app.include_router(prediccion_router.router)

# Fuerza modo claro al cargar, sin importar el tema del sistema/navegador
FORCE_LIGHT_JS = """
function() {
    const url = new URL(window.location.href);
    if (url.searchParams.get('__theme') !== 'light') {
        url.searchParams.set('__theme', 'light');
        window.location.replace(url.href);
    }
}
"""

# En Gradio 6 el CSS ya no se pasa al constructor de Blocks (solo a launch(), que aquí
# nunca se llama): en apps montadas va en mount_gradio_app.
# "/registro" y "/login" quedan fuera de auth: son las páginas públicas de entrada
app = gr.mount_gradio_app(
    app, registro_demo, path="/registro", js=FORCE_LIGHT_JS, css=CSS
)
app = gr.mount_gradio_app(app, login_demo, path="/login", js=FORCE_LIGHT_JS, css=CSS)

# "/inicio" y sus sub-páginas (subir_archivo, ver_predicciones, graficos) comparten
# la misma sesión de login porque viven en un único Blocks montado con demo.route().
app = gr.mount_gradio_app(
    app, inicio_demo, path="/inicio", auth=autenticar, js=FORCE_LIGHT_JS, css=CSS
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
