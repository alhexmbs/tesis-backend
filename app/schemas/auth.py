from pydantic import BaseModel, ConfigDict

class LoginRequest(BaseModel):
    username: str
    user_password: str

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
    usename: str
    email: str
    user_password: str