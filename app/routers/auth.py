from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.services.auth import login_service, register_service

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = login_service(request.username, request.password, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
        )

    return user


@router.post("/register", response_model=RegisterResponse)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = register_service(
            request.nombres,
            request.apellidos,
            request.dni,
            request.nro_celular,
            request.username,
            request.password,
            db,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    if user == 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El nombre de usuario ya ha sido registrado, intente con otro.",
        )

    if user == 2:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="El DNI ya ha sido registrado."
        )

    if user == 3:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El número de celular ya ha sido registrado.",
        )

    return user
