from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


# ==========================================
# SCHEMAS PARA VENTAS
# ==========================================
class VentaHistoricaBase(BaseModel):
    fecha: date
    producto: str
    cantidad: float
    precio_promedio: float

    feriado: int
    fin_de_semana: int
    es_vispera_navidad: int
    es_vispera_year_nuevo: int
    es_vispera_semana_santa: int
    es_vispera_feriado_general: int

    year: int
    mes: int
    dia: int
    dia_semana: int
    semana: int
    trimestre: int
    dia_del_year: int

    # Optional[] porque al calcular rezagos, los primeros días pueden ser nulos (NaN/Null)
    ventas_hace_1_dia: float | None = None
    ventas_hace_2_dias: float | None = None
    ventas_hace_7_dias: float | None = None
    promedio_ultimos_3_dias: float | None = None
    promedio_ultimos_7_dias: float | None = None


class VentaHistoricaCreate(VentaHistoricaBase):
    pass


class VentaHistoricaResponse(VentaHistoricaBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# ==========================================
# SCHEMAS PARA PREDICCIONES
# ==========================================
class PrediccionBase(BaseModel):
    fecha_objetivo: date
    producto: str
    cantidad_predicha: float


class PrediccionCreate(PrediccionBase):
    pass


class PrediccionResponse(PrediccionBase):
    id: int
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)
