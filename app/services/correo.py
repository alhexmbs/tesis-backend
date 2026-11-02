"""Envío de correos con Resend (https://resend.com), por su API HTTP.

Solo se usa para la recuperación de contraseña. Se llama a la API con `requests`
en vez de instalar el SDK de Resend: es una sola petición POST.
"""

import logging

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

URL_RESEND = "https://api.resend.com/emails"
TIMEOUT_S = 10


class CorreoNoEnviado(Exception):
    """Resend no está configurado o rechazó el envío."""


def enviar_correo_recuperacion(destino: str, nombre: str, enlace: str, minutos: int) -> None:
    """Envía el enlace para restablecer la contraseña. Lanza CorreoNoEnviado."""
    if not settings.resend_api_key:
        raise CorreoNoEnviado("Falta configurar RESEND_API_KEY.")

    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 480px; color: #0f172a;">
      <h2 style="color: #1d4ed8;">BENZIN AI</h2>
      <p>Hola {nombre},</p>
      <p>Recibimos una solicitud para restablecer la contraseña de tu cuenta.
         Si fuiste tú, confírmalo con el siguiente botón:</p>
      <p style="text-align: center; margin: 28px 0;">
        <a href="{enlace}" style="background: #1d4ed8; color: #ffffff; padding: 12px 22px;
           border-radius: 8px; text-decoration: none; font-weight: bold;">
          Sí, quiero cambiar mi contraseña
        </a>
      </p>
      <p>El enlace vence en {minutos} minutos y solo se puede usar una vez.</p>
      <p style="background: #fef3c7; padding: 12px; border-radius: 8px;">
        <b>¿No lo pediste tú?</b> No hagas nada: ignora este correo y tu contraseña
        seguirá siendo la misma. Nadie puede cambiarla sin este enlace.
      </p>
    </div>
    """

    try:
        resp = requests.post(
            URL_RESEND,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.correo_remitente,
                "to": [destino],
                "subject": "Restablecer tu contraseña de BENZIN AI",
                "html": html,
            },
            timeout=TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise CorreoNoEnviado(f"No se pudo conectar con Resend: {e}") from e

    if resp.status_code >= 400:
        # El detalle va al log del servidor, no al usuario.
        logger.error("Resend rechazó el correo (%s): %s", resp.status_code, resp.text)
        raise CorreoNoEnviado(f"Resend respondió {resp.status_code}.")
