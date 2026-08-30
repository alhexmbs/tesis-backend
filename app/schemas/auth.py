from pydantic import BaseModel, ConfigDict


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


class RegisterResponse(BaseModel):
    id: int
    nombres: str
    apellidos: str
    dni: str
    nro_celular: str
    username: str
    estado: bool

    model_config = ConfigDict(from_attributes=True)
