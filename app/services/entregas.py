"""Plan de entregas de combustible a partir de las ventas estimadas.

Recibe las predicciones de ``predecir_rango`` y simula el tanque.

Regla:
1. El tanque tiene stock.
2. Si al vender lo del día el stock quedaría por debajo del stock_seguridad, ese
   día llega una entrega ANTES de vender, que llena el tanque hasta el tope seguro,
   pero nunca más de lo que trae un camión (``capacidad_cisterna``).
   Llenar en cada entrega = menos entregas (fletes).
3. Se vende la venta estimada y el stock que queda pasa al día siguiente.
4. Para que la entrega llegue antes de abrir el día D hay que pagar antes de la
   hora límite de un día anterior. Con las reglas por defecto (7 h de espera,
   límite 15:00) es el día D−1: pagar el mismo día D por la mañana deja el tanque
   vacío medio día. La salida es un texto como "Pedir el lunes 13 antes de las 15:00".
   Los tiempos son parámetros de ``ReglasPedido``.

Supuesto: la entrega llega el mismo día en que se necesita, antes de abrir.
Si ya pasó la hora límite de pago, ese día no hay entrega y se marca la alerta.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

STOCK_SEGURIDAD_PCT = 15
LLENADO_MAX_PCT = {"GLP": 80}  # el GLP no se llena al 100 %
LLENADO_MAX_PCT_DEFECTO = 90  # combustibles líquidos
# Galones que trae un camión cisterna del proveedor. El de GLP va entero para GLP; el
# de líquidos (4 compartimentos) se puede compartir entre REGULAR, PREMIUM y diésel,
# pero aquí cada combustible se planifica por su lado: el sistema estima demanda, no
# arma el camión. Combinar combustibles en un mismo viaje lo decide el administrador.
CAPACIDAD_CISTERNA = {"GLP": 6_500}
CAPACIDAD_CISTERNA_DEFECTO = 4_380  # combustibles líquidos


def validar_tanque(producto: str, stock: float, capacidad: float) -> None:
    """Rechaza datos del tanque que no pueden existir. Lanza PlanImposible.

    Se usa antes de predecir (inicio.py) y al armar el plan. Para el GLP el llenado
    máximo es un límite físico de seguridad (el gas necesita espacio para
    expandirse), así que un stock por encima de él también es un dato errado. En los
    líquidos el llenado máximo es solo hasta dónde se planifica llenar: un stock
    mayor sí puede existir.
    """
    if stock < 0:
        raise PlanImposible(f"El stock ({stock:,.0f} gal) no puede ser negativo.")

    if stock > capacidad:
        raise PlanImposible(
            f"Los galones actuales ({stock:,.0f} gal) no pueden ser más que la "
            f"capacidad del tanque ({capacidad:,.0f} gal). Revisa los dos números."
        )

    if producto in LLENADO_MAX_PCT:
        pct = LLENADO_MAX_PCT[producto]
        tope = capacidad * pct / 100
        if stock > tope:
            raise PlanImposible(
                f"El tanque de {producto} solo se llena hasta el {pct:.0f} % de su "
                f"capacidad ({tope:,.0f} gal). Los galones actuales "
                f"({stock:,.0f} gal) no pueden superar ese límite."
            )


def capacidad_cisterna(producto: str) -> float:
    """Galones máximos de un pedido de ``producto`` (un camión)."""
    return CAPACIDAD_CISTERNA.get(producto, CAPACIDAD_CISTERNA_DEFECTO)



class PlanImposible(ValueError):
    """Los datos del tanque no permiten armar un plan."""

    def __init__(self, mensaje: str, detalle: str = ""):
        super().__init__(mensaje)
        self.detalle = detalle  # cifras para mostrar debajo del mensaje


@dataclass(frozen=True)
class ReglasPedido:
    """Tiempos entre pagar el pedido y tener el combustible en el tanque."""

    horas_entrega: float = 7.0  # promedio entre pago y descarga
    hora_limite_pago: time = time(15, 0)  # después de esto, la carga pasa al día siguiente
    hora_inicio_carga: time = time(7, 0)  # a qué hora empieza a cargarse al día siguiente
    hora_apertura: time = time(7, 0)  # el combustible debe estar antes de esto

    def hora_llegada(self, pago: datetime) -> datetime:
        """Cuándo llega el combustible si se paga en el momento pago."""
        if pago.time() > self.hora_limite_pago:
            pago = datetime.combine(
                pago.date() + timedelta(days=1), self.hora_inicio_carga
            )
        return pago + timedelta(hours=self.horas_entrega)

    @property
    def dias_anticipacion(self) -> int:
        """Días antes de la entrega en que hay que pagar (a la hora límite)."""
        dia = date(2000, 1, 10)
        apertura = datetime.combine(dia, self.hora_apertura)
        for k in range(4):
            pago = datetime.combine(dia - timedelta(days=k), self.hora_limite_pago)
            if self.hora_llegada(pago) <= apertura:
                return k
        raise ValueError(
            "Con esos tiempos ninguna entrega llega antes de abrir. "
            "Revisa horas_entrega y hora_apertura."
        )

    def limite_de_pago(self, fecha_entrega: date) -> datetime:
        """Último momento para pagar y recibir el combustible al abrir ``fecha_entrega``."""
        dia_pago = fecha_entrega - timedelta(days=self.dias_anticipacion)
        return datetime.combine(dia_pago, self.hora_limite_pago)


## Funciones utilitarias.
def _texto_pedido(limite: datetime) -> str:
    return (
        f"Pedir el {DIAS_SEMANA[limite.weekday()]} {limite.day} "
        f"antes de las {limite:%H:%M}"
    )


def planificar_entregas(
    producto: str,
    ventas: list[tuple[date, float]],
    stock_inicial: float,
    capacidad: float,
    ahora: datetime | None = None,
    reglas: ReglasPedido = ReglasPedido(),
) -> dict:
    """Simula el tanque y devuelve qué días recibir combustible, cuánto y cuándo pedirlo.

        ventas: lista de (fecha, galones estimados), en orden.
        ahora: momento en que se consulta el plan. Si se da, no se planean pedidos
            cuya hora límite de pago ya pasó. Si es None, se asume que siempre hay tiempo.
        reglas: tiempos de entrega y pago.

    Devuelve
        dias: una fila por día. Cada fila trae fecha, stock_al_abrir, entrega,
            venta, vendido, faltante, stock_al_cerrar, pagar_antes_de (datetime
            o None), pedido (texto o "") y alerta ("", "bajo_reserva" o "quiebre"),
        entregas: solo los días con entrega,
        alertas: solo los días con alerta,
        total_pedido,
        stock_final,
        tope (galones a los que se llena).
    """

    stock_seguridad = capacidad * STOCK_SEGURIDAD_PCT / 100
    llenado_max_pct = LLENADO_MAX_PCT.get(producto, LLENADO_MAX_PCT_DEFECTO)
    tope = capacidad * llenado_max_pct / 100

    # Validaciones: sin ellas el bucle dejaría el tanque en negativo.
    validar_tanque(producto, stock_inicial, capacidad)

    # Con el 15 % y los topes fijos de arriba esto no se dispara, pero queda
    # como protección por si el stock de seguridad pasa a ser un parámetro.
    if stock_seguridad >= tope:
        raise PlanImposible(
            f"La reserva mínima es mayor de lo que cabe en el tanque. "
            f"Redúcela a menos de {tope:,.0f} gal.",
            detalle=(
                f"Reserva mínima: {stock_seguridad:,.0f} gal · "
                f"Tanque al {llenado_max_pct:.0f} %: {tope:,.0f} gal"
            ),
        )

    disponible = tope - stock_seguridad
    cisterna = capacidad_cisterna(producto)
    for fecha, venta in ventas:
        # Con un camión por día no se puede reponer más de lo que trae: si la venta
        # del día lo supera, el tanque se vaciaría aunque se pida todos los días.
        if venta > cisterna:
            raise PlanImposible(
                f"El {fecha:%d/%m} se venderían {venta:,.0f} gal, más de los "
                f"{cisterna:,.0f} gal que trae un camión. Haría falta más de un "
                "camión por día.",
            )
        if venta > disponible:
            raise PlanImposible(
                f"El {fecha:%d/%m} se venderían {venta - disponible:,.0f} gal más de los "
                "que el tanque puede entregar en un día. Necesitarías 2 despachos "
                "ese día o bajar la reserva mínima.",
                detalle=(
                    f"Venta proyectada: {venta:,.0f} gal · "
                    f"Tanque al {llenado_max_pct:.0f} %: {tope:,.0f} gal · "
                    f"Reserva mínima: {stock_seguridad:,.0f} gal · "
                    f"Disponible: {disponible:,.0f} gal"
                ),
            )

    stock = stock_inicial
    dias = []
    for fecha, venta in ventas:
        stock_al_abrir = stock
        entrega = 0.0
        pagar_antes_de = None
        pedido = ""
        necesita_entrega = stock - venta < stock_seguridad

        if necesita_entrega:
            limite = reglas.limite_de_pago(fecha)
            if ahora is None or limite >= ahora:
                # Hasta el tope del tanque, pero como máximo un camión.
                entrega = min(max(tope - stock, 0.0), cisterna)
                stock += entrega
                if entrega > 0:
                    pagar_antes_de = limite
                    pedido = _texto_pedido(limite)
            # Si ya pasó el límite, no hay entrega: se vende con lo que hay.

        vendido = min(venta, stock)  # el tanque no puede quedar en negativo
        faltante = venta - vendido
        stock -= vendido

        if faltante > 0:
            alerta = "quiebre"
        elif entrega == 0 and stock < stock_seguridad:
            alerta = "bajo_reserva"
        else:
            alerta = ""

        dias.append(
            {
                "fecha": fecha,
                "stock_al_abrir": stock_al_abrir,
                "entrega": entrega,
                "venta": venta,
                "vendido": vendido,
                "faltante": faltante,
                "stock_al_cerrar": stock,
                "pagar_antes_de": pagar_antes_de,
                "pedido": pedido,
                "alerta": alerta,
            }
        )

    entregas = [d for d in dias if d["entrega"] > 0]
    return {
        "dias": dias,
        "entregas": entregas,
        "alertas": [d for d in dias if d["alerta"]],
        "total_pedido": sum(d["entrega"] for d in entregas),
        "stock_final": stock,
        "tope": tope,
    }
