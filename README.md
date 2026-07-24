# Backend - BENZIN AI

Este repositorio contiene el backend de la aplicación diseñada para procesar, limpiar y almacenar datos de ventas diarias de los hidrocarburos del gripo Gran Prix. El sistema está optimizado para generar características temporales (Time Series Feature Engineering) y preparar la data para el modelo de predicción.

## Tecnologías

- **[FastAPI](https://fastapi.tiangolo.com/):** Framework web moderno y rápido para construir la API.
- **[Pandas](https://pandas.pydata.org/):** Librería principal para el procesamiento de datos y cálculo de promedios móviles/lags.
- **[SQLAlchemy](https://www.sqlalchemy.org/):** ORM (Object Relational Mapper) para la interacción con la base de datos PostgreSQL.
- **[holidays](https://python-holidays.readthedocs.io/):** Librería para el cálculo dinámico de feriados nacionales en Perú.
- **[uv](https://github.com/astral-sh/uv):** Gestor de paquetes y entornos virtuales de Python extremadamente rápido.

## Características Core

El corazón de este backend es su pipeline de procesamiento continuo de datos (ubicado en `app/services/limpieza.py`):

1. **Carga y limpieza básica:** Lee reportes de ventas en formato Excel `.xlsx`, agrupa los datos de manera diaria y extrae los tipos de combustible (BIODIESEL, GLP, REGULAR, PREMIUM).
2. **Contexto histórico continuo:** Antes de calcular variables de rezago, el pipeline consulta los últimos 7 días registrados en la base de datos para concatenarlos con el nuevo archivo. Esto evita la pérdida de datos (NaN) al inicio del nuevo lote.
3. **Ingeniería de características temporales:**
   - **Lags (Rezagos):** Ventas de hace 1, 2 y 7 días.
   - **Medias móviles (Rolling Averages):** Promedio de ventas de los últimos 3 y 7 días.
4. **Cálculo dinámico de feriados:** Utiliza la librería `holidays.PE()` para identificar matemáticamente días festivos oficiales de Perú y sus vísperas (ej. Navidad, Jueves Santo), sin necesidad de mantener un archivo estático.
5. **Carga a base de datos:** Finalmente, descarta las fechas de apoyo histórico e inserta únicamente los nuevos registros enriquecidos en la base de datos de PostgreSQL.

## Estructura del proyecto

```text
backend/
├── app/
│   ├── core/           # Configuraciones principales (CORS, variables de entorno)
│   ├── data/           # Archivos estáticos o de soporte
│   ├── models/         # Modelos de base de datos SQLAlchemy (ej. ventas.py)
│   ├── routers/        # Endpoints de la API (ej. ventas.py)
│   ├── schemas/        # Esquemas de Pydantic para validación de datos
│   ├── services/       # Lógica de negocio y procesamiento (limpieza.py)
│   ├── database.py     # Configuración de la conexión a la Base de Datos
│   └── main.py         # Punto de entrada de FastAPI
├── pyproject.toml      # Configuración de dependencias
├── uv.lock             # Archivo de bloqueo de dependencias de uv
└── README.md           # Documentación
```

## Instalación y ejecución local

Asegúrate de tener instalado [uv](https://github.com/astral-sh/uv) en tu sistema.

1. **Clonar el repositorio y entrar a la carpeta backend:**
   ```bash
   cd tesis/backend
   ```

2. **Crear el entorno virtual e instalar las dependencias:**
   ```bash
   uv sync
   ```

3. **Configurar variables de entorno:**
   Asegúrate de que exista un archivo `.env` en la raíz de `backend/` con las credenciales de tu base de datos PostgreSQL.

4. **Ejecutar el servidor de desarrollo:**
   ```bash
   uv run uvicorn app.main:app --reload
   ```
   *(El servidor estará disponible en `http://localhost:8000`. Puedes ver la documentación interactiva de la API en `http://localhost:8000/docs`)*

## Endpoints principales

- `POST /api/v1/ventas/upload`: Recibe un archivo Excel, lo procesa a través del pipeline de limpieza y almacena los datos enriquecidos en la base de datos.
