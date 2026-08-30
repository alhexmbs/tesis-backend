"""Exporta toda la tabla ventas_historicas a un CSV para análisis exploratorio.

Uso:
    uv run python scripts/exportar_ventas_historicas.py [ruta_salida.csv]

Si no se indica ruta_salida, se guarda en data/ventas_historicas.csv
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import engine

RUTA_SALIDA_DEFAULT = (
    Path(__file__).resolve().parent.parent / "data" / "ventas_historicas.csv"
)


def main() -> None:
    ruta_salida = Path(sys.argv[1]) if len(sys.argv) > 1 else RUTA_SALIDA_DEFAULT
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_sql_table("ventas_historicas", con=engine)
    df = df.sort_values(["producto", "fecha"]).reset_index(drop=True)
    df.to_csv(ruta_salida, index=False, encoding="utf-8-sig")

    print(f"{len(df)} filas exportadas a {ruta_salida}")


if __name__ == "__main__":
    main()
