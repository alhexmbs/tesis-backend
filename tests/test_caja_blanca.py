"""Pruebas de caja blanca (técnica del camino básico de McCabe).

Cada prueba recorre UN camino independiente del grafo de flujo de su función. Los
identificadores (PB-01-C1, ...) son los del documento "Pruebas de caja blanca".

Ejecutar desde la carpeta backend:
    uv run python -m pytest tests/test_caja_blanca.py -v

(con "python -m" la carpeta actual entra al path y se puede importar "app").

No usan la base de datos real: donde la función consulta la base, se le pasa un
objeto falso que devuelve el usuario preparado para ese camino.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import app.ui.auth as ui_auth
from app.services.auth import _ahora_utc, usuario_por_token
from app.services.entregas import PlanImposible, validar_tanque
from app.services.prediccion.features import HistorialInsuficiente
from app.services.prediccion.servicio import MAX_HORIZONTE_DIAS, _validar_horizonte
from app.utils.validaciones import ErrorValidacion, validar_dni


# --------------------------------------------------------------------------- #
# PB-01  validar_tanque (app/services/entregas.py)  —  V(G) = 5
# --------------------------------------------------------------------------- #
def test_pb01_c1_stock_negativo():
    # Camino 1-2-8
    with pytest.raises(PlanImposible, match="no puede ser negativo"):
        validar_tanque("REGULAR", -10, 1000)


def test_pb01_c2_stock_mayor_que_capacidad():
    # Camino 1-3-4-8
    with pytest.raises(PlanImposible, match="no pueden ser más que la capacidad"):
        validar_tanque("REGULAR", 1200, 1000)


def test_pb01_c3_liquido_valido():
    # Camino 1-3-5-8: REGULAR no tiene tope de llenado
    assert validar_tanque("REGULAR", 500, 1000) is None


def test_pb01_c4_glp_supera_80_por_ciento():
    # Camino 1-3-5-6-7-8: tope = 1000 * 80 % = 800
    with pytest.raises(PlanImposible, match="80 %"):
        validar_tanque("GLP", 900, 1000)


def test_pb01_c5_glp_valido():
    # Camino 1-3-5-6-8
    assert validar_tanque("GLP", 700, 1000) is None


# --------------------------------------------------------------------------- #
# PB-02  usuario_por_token (app/services/auth.py)  —  V(G) = 5
# --------------------------------------------------------------------------- #
class _DbFalsa:
    """Imita Session.scalar: devuelve siempre el usuario que se le indique."""

    def __init__(self, usuario):
        self.usuario = usuario

    def scalar(self, _stmt):
        return self.usuario


def test_pb02_c1_token_vacio():
    # Camino 1-2-9: ni siquiera consulta la base
    assert usuario_por_token("", _DbFalsa(object())) is None


def test_pb02_c2_token_inexistente():
    # Camino 1-3-5-9
    assert usuario_por_token("abc123", _DbFalsa(None)) is None


def test_pb02_c3_usuario_sin_vencimiento():
    # Camino 1-3-4-5-9
    user = SimpleNamespace(reset_token_expira=None)
    assert usuario_por_token("abc123", _DbFalsa(user)) is None


def test_pb02_c4_token_vencido():
    # Camino 1-3-4-6-7-9
    user = SimpleNamespace(reset_token_expira=_ahora_utc() - timedelta(minutes=1))
    assert usuario_por_token("abc123", _DbFalsa(user)) is None


def test_pb02_c5_token_vigente():
    # Camino 1-3-4-6-8-9
    user = SimpleNamespace(reset_token_expira=_ahora_utc() + timedelta(minutes=30))
    assert usuario_por_token("abc123", _DbFalsa(user)) is user


# --------------------------------------------------------------------------- #
# PB-03  _verificar (app/ui/auth.py)  —  V(G) = 3
# --------------------------------------------------------------------------- #
@pytest.fixture
def sin_fallos():
    ui_auth._fallos.clear()
    yield
    ui_auth._fallos.clear()


def test_pb03_c1_usuario_bloqueado(sin_fallos, monkeypatch):
    # Camino 1-2-7: con 5 fallos recientes ni se consulta la contraseña
    llamadas = []
    monkeypatch.setattr(ui_auth, "login_service", lambda *a: llamadas.append(a))
    ui_auth._fallos["admin"] = (ui_auth.MAX_INTENTOS, ui_auth.time.monotonic())

    assert ui_auth._verificar("admin", "ClaveCorrecta#2026", db=None) is None
    assert llamadas == []


def test_pb03_c2_password_correcta(sin_fallos, monkeypatch):
    # Camino 1-3-4-6-7: entra y se borra su contador de fallos
    user = SimpleNamespace(username="admin")
    monkeypatch.setattr(ui_auth, "login_service", lambda *a: user)
    ui_auth._fallos["admin"] = (2, ui_auth.time.monotonic())

    assert ui_auth._verificar("admin", "ClaveCorrecta#2026", db=None) is user
    assert "admin" not in ui_auth._fallos


def test_pb03_c3_password_incorrecta(sin_fallos, monkeypatch):
    # Camino 1-3-5-6-7: no entra y se cuenta un fallo
    monkeypatch.setattr(ui_auth, "login_service", lambda *a: None)

    assert ui_auth._verificar("admin", "equivocada", db=None) is None
    assert ui_auth._fallos["admin"][0] == 1


# --------------------------------------------------------------------------- #
# PB-04  validar_dni (app/utils/validaciones.py)  —  V(G) = 4
# --------------------------------------------------------------------------- #
def test_pb04_c1_dni_vacio():
    # Camino 1-2-8
    with pytest.raises(ErrorValidacion, match="no puede estar vacío"):
        validar_dni("   ")


def test_pb04_c2_dni_con_letras():
    # Camino 1-3-4-8
    with pytest.raises(ErrorValidacion, match="solo admite números"):
        validar_dni("12a45678")


def test_pb04_c3_dni_largo_incorrecto():
    # Camino 1-3-5-6-8
    with pytest.raises(ErrorValidacion, match="exactamente 8 dígitos"):
        validar_dni("1234567")


def test_pb04_c4_dni_valido():
    # Camino 1-3-5-7-8: además quita los espacios de los extremos
    assert validar_dni(" 12345678 ") == "12345678"


# --------------------------------------------------------------------------- #
# PB-05  _validar_horizonte (app/services/prediccion/servicio.py)  —  V(G) = 2
# --------------------------------------------------------------------------- #
def test_pb05_c1_fecha_fuera_del_horizonte():
    # Camino 1-2-3: 16 días después del último día con ventas
    ultimo = date(2026, 10, 30)
    with pytest.raises(HistorialInsuficiente, match="como máximo 15 días"):
        _validar_horizonte("GLP", ultimo, ultimo + timedelta(days=16), 16)


def test_pb05_c2_fecha_en_el_limite():
    # Camino 1-3: justo 15 días (valor límite) sí se permite
    ultimo = date(2026, 10, 30)
    assert MAX_HORIZONTE_DIAS == 15
    assert _validar_horizonte("GLP", ultimo, ultimo + timedelta(days=15), 15) is None
