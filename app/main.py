from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine
from app.models import ventas
from app.routers import ventas as ventas_router

ventas.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="API BENZIN AI",
    description="Backend for BENZIN AI",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # en producción poner la url de angular
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ventas_router.router)

@app.get("/")
def health_check():
    return {"message": "backend working"}