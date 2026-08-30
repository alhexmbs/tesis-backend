import gradio as gr

from app.ui.auth import autenticar
from app.ui.cargar_ventas import demo as cargar_ventas_demo

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

app = gr.mount_gradio_app(app, cargar_ventas_demo, path="/ui", auth=autenticar)

@app.get("/")
def health_check():
    return {"message": "backend working"}
