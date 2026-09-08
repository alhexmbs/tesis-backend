from pydantic import BaseModel, ConfigDict, field_validator

from app.utils.validaciones import (
    validar_dni,
    validar_nombre,
    validar_nro_celular,
    validar_username,
)


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    id: int
    nombres: str
    apellidos: str
    username: str
    estado: bool

    model_config = ConfigDict(from_attributes=True)


class RegisterRequest(BaseModel):
    nombres: str
    apellidos: str
    dni: str
    nro_celular: str
    username: str
    password: str

    # Las mismas reglas que aplica `register_service`, adelantadas al parseo del body
    # para que la API responda 422 con el campo señalado en vez de un 400 genérico.
    # La contraseña no se valida aquí: zxcvbn necesita el resto de los datos.
    @field_validator("nombres")
    @classmethod
    def _v_nombres(cls, v: str) -> str:
        return validar_nombre(v, "nombres", "Los nombres")

    @field_validator("apellidos")
    @classmethod
    def _v_apellidos(cls, v: str) -> str:
        return validar_nombre(v, "apellidos", "Los apellidos")

    @field_validator("dni")
    @classmethod
    def _v_dni(cls, v: str) -> str:
        return validar_dni(v)

    @field_validator("nro_celular")
    @classmethod
    def _v_nro_celular(cls, v: str) -> str:
        return validar_nro_celular(v)

    @field_validator("username")
    @classmethod
    def _v_username(cls, v: str) -> str:
        return validar_username(v)


class RegisterResponse(BaseModel):
    id: int
    nombres: str
    apellidos: str
    dni: str
    nro_celular: str
    username: str
    estado: bool

    model_config = ConfigDict(from_attributes=True)
