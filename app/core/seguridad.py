import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

# La API REST (/api/...) es solo para el administrador: crear cuentas, probar
# predicciones o cargar ventas desde /docs. Cada petición debe traer la clave en el
# header X-API-Key. La UI de Gradio no pasa por aquí: llama a los servicios directo.
# Usar APIKeyHeader hace que /docs muestre el botón "Authorize" para poner la clave.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verificar_api_key(api_key: str | None = Security(api_key_header)) -> None:
    # Sin API_KEY configurada se cierra todo en vez de dejar la API abierta.
    if not settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API deshabilitada: falta configurar API_KEY en el servidor.",
        )

    # compare_digest tarda lo mismo acierte o no: no deja adivinar la clave
    # carácter por carácter midiendo tiempos de respuesta. Se compara en bytes porque
    # con str solo acepta ASCII y una clave con tildes lanzaría error (500).
    if not api_key or not secrets.compare_digest(
        api_key.encode(), settings.api_key.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o ausente.",
        )
