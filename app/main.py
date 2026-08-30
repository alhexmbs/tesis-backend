import gradio as gr
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.models import (
    datos_meteorologicos,
    indice_precio_combustibles,
    precio_wti,
    prediccion,
    tipo_cambio,
    usuarios,
    ventas,
)
from app.routers import auth as auth_router
from app.routers import etl as etl_router
from app.ui.auth import autenticar
from app.ui.inicio import demo as inicio_demo
from app.ui.login import demo as login_demo
from app.ui.registro import demo as registro_demo

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="API BENZIN AI", description="Backend for BENZIN AI", version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # en producción poner la url de angular
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(etl_router.router)

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

# "/registro" y "/login" quedan fuera de auth: son las páginas públicas de entrada
app = gr.mount_gradio_app(app, registro_demo, path="/registro", js=FORCE_LIGHT_JS)
app = gr.mount_gradio_app(app, login_demo, path="/login", js=FORCE_LIGHT_JS)

# "/inicio" y sus sub-páginas (subir_archivo, ver_predicciones, graficos) comparten
# la misma sesión de login porque viven en un único Blocks montado con demo.route().
app = gr.mount_gradio_app(
    app, inicio_demo, path="/inicio", auth=autenticar, js=FORCE_LIGHT_JS
)


@app.get("/")
def health_check():
    return {"message": "backend working"}
