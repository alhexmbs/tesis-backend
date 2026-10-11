"""Validaciones de los campos del registro de usuario.

Viven aquí y no en el schema de Pydantic para que `register_service` las aplique
siempre, venga de donde venga la llamada. Hoy la única entrada es el router
`/api/auth/register`: la UI no tiene registro, las cuentas las crea el administrador.

`ErrorValidacion` hereda de `ValueError` a propósito: el router ya captura
`ValueError` y responde 400; el atributo `campo` indica qué dato falló.
"""

import re
from datetime import date

# Letras (con tildes y ñ), espacios, apóstrofo y guion: "D'Angelo", "Vargas-Llosa".
_NOMBRE_RE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ' -]*$")
_SOLO_DIGITOS_RE = re.compile(r"^\d+$")
_FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

LARGO_DNI = 8
LARGO_CELULAR = 9


class ErrorValidacion(ValueError):
    """Mensaje de validación asociado a un campo concreto del formulario."""

    def __init__(self, campo: str, mensaje: str):
        super().__init__(mensaje)
        self.campo = campo


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def validar_nombre(valor, campo: str, etiqueta: str) -> str:
    valor = _texto(valor)
    if not valor:
        raise ErrorValidacion(campo, f"{etiqueta} no puede estar vacío.")
    if any(c.isdigit() for c in valor):
        raise ErrorValidacion(campo, f"{etiqueta} no puede contener números.")
    if not _NOMBRE_RE.match(valor):
        raise ErrorValidacion(
            campo, f"{etiqueta} solo admite letras, espacios, apóstrofo y guion."
        )
    if len(valor) > 60:
        raise ErrorValidacion(campo, f"{etiqueta} no puede superar los 60 caracteres.")
    return valor


def validar_dni(valor) -> str:
    valor = _texto(valor)
    if not valor:
        raise ErrorValidacion("dni", "El DNI no puede estar vacío.")
    if not _SOLO_DIGITOS_RE.match(valor):
        raise ErrorValidacion(
            "dni", "El DNI solo admite números, sin letras ni signos."
        )
    if len(valor) != LARGO_DNI:
        raise ErrorValidacion(
            "dni", f"El DNI debe tener exactamente {LARGO_DNI} dígitos."
        )
    return valor


def validar_nro_celular(valor) -> str:
    valor = _texto(valor)
    if not valor:
        raise ErrorValidacion(
            "nro_celular", "El número de celular no puede estar vacío."
        )
    if not _SOLO_DIGITOS_RE.match(valor):
        raise ErrorValidacion(
            "nro_celular",
            "El número de celular solo admite números, sin letras ni signos.",
        )
    if len(valor) != LARGO_CELULAR:
        raise ErrorValidacion(
            "nro_celular",
            f"El número de celular debe tener exactamente {LARGO_CELULAR} dígitos.",
        )
    return valor


def validar_username(valor) -> str:
    valor = _texto(valor)
    if not valor:
        raise ErrorValidacion("username", "El usuario no puede estar vacío.")
    if len(valor) < 4 or len(valor) > 30:
        raise ErrorValidacion(
            "username", "El usuario debe tener entre 4 y 30 caracteres."
        )
    return valor


def validar_fecha(valor, campo: str = "fecha") -> date:
    """Fecha en formato AAAA-MM-DD. Rechaza letras antes de intentar parsearla."""
    valor = _texto(valor)
    if not valor:
        raise ErrorValidacion(campo, "La fecha no puede estar vacía.")
    if any(c.isalpha() for c in valor):
        raise ErrorValidacion(
            campo, "La fecha no admite letras. Usa el formato AAAA-MM-DD."
        )
    if not _FECHA_RE.match(valor):
        raise ErrorValidacion(campo, "Formato de fecha inválido. Usa AAAA-MM-DD.")
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErrorValidacion(campo, "Esa fecha no existe en el calendario.") from None


def validar_datos_registro(nombres, apellidos, dni, nro_celular, username) -> dict:
    """Valida y normaliza los campos del registro. Lanza `ErrorValidacion` al primer fallo."""
    return {
        "nombres": validar_nombre(nombres, "nombres", "Los nombres"),
        "apellidos": validar_nombre(apellidos, "apellidos", "Los apellidos"),
        "dni": validar_dni(dni),
        "nro_celular": validar_nro_celular(nro_celular),
        "username": validar_username(username),
    }
