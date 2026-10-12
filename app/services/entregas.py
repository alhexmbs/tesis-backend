"""Plan de entregas de combustible a partir de la venta estimada día por día.

No toca el modelo: recibe las predicciones de ``predecir_rango`` y simula el tanque.

Regla, día por día:
1. Por la mañana el tanque tiene ``stock``.
2. Si al vender lo del día el stock quedaría por debajo del ``stock_minimo``, ese
   día llega una entrega ANTES de vender, que llena el tanque hasta el tope seguro
   (capacidad × llenado máximo %). Llenar en cada entrega = menos entregas (fletes).
3. Se vende la venta estimada y el stock que queda pasa al día siguiente.

Supuesto: la entrega llega el mismo día en que se necesita, antes de abrir. Si el
proveedor demora, hay que llamarlo con anticipación (lo dice la UI).
"""

from datetime import date


class PlanImposible(ValueError):
    """Los datos del tanque no permiten armar un plan (mensaje en lenguaje llano)."""


def planificar_entregas(
    ventas: list[tuple[date, float]],
    stock_inicial: float,
    capacidad: float,
    llenado_max_pct: float = 95,
    stock_minimo: float = 0,
) -> dict:
    """Simula el tanque y devuelve qué días recibir combustible y cuánto.

    ``ventas``: lista de (fecha, galones estimados), en orden.
    Devuelve ``dias`` (una fila por día), ``entregas`` (solo los días con entrega),
    ``total_pedido``, ``stock_final`` y ``tope`` (galones a los que se llena).
    """
    tope = capacidad * llenado_max_pct / 100

    # Validaciones: sin ellas el bucle dejaría el tanque en negativo.
    if stock_inicial > capacidad:
        raise PlanImposible(
            f"El stock ({stock_inicial:,.0f} gal) es mayor que la capacidad del "
            f"tanque ({capacidad:,.0f} gal). Revisa los dos números."
        )
    if stock_minimo >= tope:
        raise PlanImposible(
            f"El stock mínimo ({stock_minimo:,.0f} gal) no puede ser igual o mayor que "
            f"lo que cabe en el tanque lleno al {llenado_max_pct:.0f} % "
            f"({tope:,.0f} gal)."
        )
    for fecha, venta in ventas:
        if venta > tope - stock_minimo:
            raise PlanImposible(
                f"El {fecha:%d/%m/%Y} se venderían {venta:,.0f} gal, más de lo que "
                f"el tanque puede entregar en un día ({tope - stock_minimo:,.0f} gal entre el "
                "tope y el stock mínimo). Haría falta más de una entrega ese día."
            )

    stock = stock_inicial
    dias = []
    for fecha, venta in ventas:
        stock_al_abrir = stock
        entrega = 0.0
        if stock - venta < stock_minimo:
            entrega = max(tope - stock, 0.0)
            stock += entrega
        stock -= venta
        dias.append(
            {
                "fecha": fecha,
                "stock_al_abrir": stock_al_abrir,
                "entrega": entrega,
                "venta": venta,
                "stock_al_cerrar": stock,
            }
        )

    entregas = [d for d in dias if d["entrega"] > 0]
    return {
        "dias": dias,
        "entregas": entregas,
        "total_pedido": sum(d["entrega"] for d in entregas),
        "stock_final": stock,
        "tope": tope,
    }
