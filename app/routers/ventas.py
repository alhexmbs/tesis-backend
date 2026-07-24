from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.ventas import VentaHistorica
from app.services.limpieza import procesar_excel_ventas

router = APIRouter(prefix="/api/v1/ventas", tags=["Ventas"])

@router.post("/upload")
async def subir_reporte_ventas(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="El archivo debe ser un Excel (.xlsx)")
    
    try:
        contenido = await file.read()
        # 1. Traer los últimos 7 días de la base de datos (nuestro lag máximo)
        # Esto sirve de "ancla" para los cálculos móviles del nuevo archivo.
        query_historico = db.query(
            VentaHistorica.fecha, 
            VentaHistorica.producto, 
            VentaHistorica.cantidad
        ).order_by(VentaHistorica.fecha.desc()).limit(7 * 4) # 7 días x 4 productos
        
        resultados = query_historico.all()
        historico_dicts = [
            {"fecha": r.fecha, "producto": r.producto, "cantidad": r.cantidad}
            for r in resultados
        ]
        
        datos_limpios = procesar_excel_ventas(contenido, historico_dicts)
        
        nuevos_registros = []
        for fila in datos_limpios:
            nueva_venta = VentaHistorica(**fila)
            db.add(nueva_venta)
            nuevos_registros.append(nueva_venta)
            
        db.commit()
        
        return {
            "message": "Archivo procesado y guardado con éxito", 
            "filas_insertadas": len(nuevos_registros)
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al procesar el archivo: {str(e)}")