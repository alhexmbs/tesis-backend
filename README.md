# BENZIN AI — Backend

Sistema de **predicción de demanda diaria de combustible** para un grifo en
Lambayeque, Perú. Estima cuántos galones de **REGULAR, PREMIUM y GLP** se venderán
por día y, a partir de esa estimación, sugiere **cuánto y qué día pedir** al
proveedor según el stock y la capacidad del tanque.

Un solo proceso FastAPI sirve dos cosas:

- **Interfaz web (Gradio)** para el encargado del grifo: login, predicción diaria,
  predicción de rango con plan de entregas, carga del reporte mensual de ventas y
  métricas del modelo en lenguaje llano.
- **API REST** (`/api/...`) con los mismos servicios, para un frontend externo.

> Diagramas de la arquitectura (capas, flujo de predicción, ETL, login, base de
> datos, plan de entregas): [`docs/arquitectura.md`](docs/arquitectura.md).

---

## Funcionalidades

| Pestaña | Qué hace |
|---|---|
| **Predicción diaria** | Galones estimados para un producto y una fecha (desde hoy hasta 15 días después del último día con ventas cargadas). |
| **Predicción de rango** | Galones día por día para 1–15 días, con gráfico. Con el stock y la capacidad del tanque arma un **plan de entregas**: qué días recibir combustible y cuánto. |
| **Cargar ventas mensuales** | Sube uno o varios reportes `.xlsx` del sistema del grifo y los agrega al historial (idempotente: volver a subir un mes lo actualiza, no lo duplica). |
| **Métricas del modelo** | Error medio en galones y en %, junto a la venta diaria del producto, y cuánto mejora frente al método simple de repetir la venta de la semana pasada. |

## Cómo predice el modelo

- Un modelo **Ridge** (`StandardScaler` + `Ridge`) por producto, entrenado en los
  notebooks de la tesis y guardado en `app/artefactos/modelos/*.joblib`.
- El modelo no predice galones directamente, sino la **razón** frente al promedio
  de los 28 días anteriores:

  ```
  galones = max(modelo.predict(features) × base_28, 0)
  ```

- Usa **17 features** (`app/services/prediccion/features.py`, copia fiel del
  notebook): calendario y feriados de Perú, vísperas, temperatura máxima, rezagos
  de 1/7/14 días, media y volatilidad de la última semana, transacciones, precio y
  régimen de precio.
- La **temperatura** viene del pronóstico de [Open-Meteo](https://open-meteo.com)
  (sin API key), con una sola petición guardada 1 hora en memoria. Si falla, se usa
  el promedio histórico del mes. El modelo la usa, pero la interfaz no la muestra.
- El reporte de ventas llega mensual: los días entre el último dato cargado y la
  fecha pedida se **estiman con el propio modelo** (máximo 15 días), nunca se
  rellenan con ceros.

### Desempeño (holdout de 90 días que el modelo no vio al evaluar)

| Producto | Error medio | Error medio (%) | Menos error que el método simple* |
|---|---|---|---|
| GLP | 138 gal/día | 4.7 % | 15 % |
| REGULAR | 74 gal/día | 9.3 % | 21 % |
| PREMIUM | 53 gal/día | 11.4 % | 34 % |

\* Método simple (naive estacional): repetir lo vendido el mismo día de la semana
anterior. Los números salen de `app/artefactos/config_servicio.json`. Además hay un
backtesting de 38 meses con reentrenamiento mensual en los notebooks de la tesis.

---

## Tecnologías

| | |
|---|---|
| Web / API | [FastAPI](https://fastapi.tiangolo.com/), [Gradio](https://www.gradio.app/) 6 |
| Datos | [pandas](https://pandas.pydata.org/), [holidays](https://python-holidays.readthedocs.io/) (feriados de Perú) |
| Modelo | [scikit-learn](https://scikit-learn.org/), joblib |
| Base de datos | PostgreSQL con [SQLAlchemy](https://www.sqlalchemy.org/) 2 + psycopg 3 |
| Seguridad | pwdlib (argon2) para contraseñas, zxcvbn para su fortaleza, `X-API-Key` en la API |
| Entorno | Python 3.12, [uv](https://github.com/astral-sh/uv) |
| Despliegue | [Railway](https://railway.com) (`railway.json`) |

## Estructura del proyecto

```text
backend/
├── app/
│   ├── main.py                 # Punto de entrada: FastAPI + monta las páginas Gradio
│   ├── database.py             # Motor y sesiones de SQLAlchemy
│   ├── core/
│   │   ├── config.py           # Variables de entorno y rutas de artefactos
│   │   └── seguridad.py        # Verificación del header X-API-Key
│   ├── models/                 # Tablas: usuarios, historial_ventas
│   ├── schemas/                # Validación de JSON de la API (Pydantic)
│   ├── routers/                # Endpoints REST: auth.py, prediccion.py
│   ├── services/
│   │   ├── auth.py             # Registro y login
│   │   ├── entregas.py         # Plan de entregas (stock, capacidad, stock mínimo)
│   │   └── prediccion/
│   │       ├── servicio.py     # Predicción diaria, de rango, métricas
│   │       ├── features.py     # Las 17 features (copia fiel del notebook)
│   │       ├── clima.py        # Temperatura de Open-Meteo con respaldo
│   │       ├── ingesta.py      # ETL del reporte mensual (.xlsx → historial)
│   │       ├── extraccion.py   #   Extract
│   │       └── agregacion.py   #   Transform (día × producto)
│   ├── ui/
│   │   ├── paginas/            # login.py, inicio.py (pestañas de la app)
│   │   ├── componentes.py      # Tema, mensajes en bloque de color, fechas
│   │   ├── calendario.py       # Selector de fecha (Flatpickr)
│   │   └── static/             # CSS, JS y librerías locales (sin CDN)
│   ├── utils/                  # Validaciones y contraseñas
│   └── artefactos/
│       ├── modelos/            # REGULAR.joblib, PREMIUM.joblib, GLP.joblib
│       ├── config_servicio.json# Orden de features, régimen de precio, métricas
│       └── historial_semilla.csv # Historial diario exportado del notebook
├── docs/arquitectura.md        # Diagramas Mermaid para estudiar el sistema
├── pyproject.toml / uv.lock    # Dependencias (gestionadas con uv)
└── railway.json                # Comando de arranque en Railway
```

---

## Instalación y ejecución local

Requisitos: [uv](https://github.com/astral-sh/uv) y una base PostgreSQL accesible.

1. **Instalar dependencias** (uv crea el entorno virtual con Python 3.12):

   ```bash
   cd backend
   uv sync
   ```

2. **Crear `.env`** en la raíz de `backend/`:

   ```env
   DB_HOST=localhost
   DB_PORT=5432
   DB_NAME=benzin
   DB_USER=postgres
   DB_PASSWORD=tu_contraseña
   API_KEY=una_clave_larga_y_secreta
   DEBUG=false
   ```

   `API_KEY` protege toda la API REST; si falta, la API responde 503 (la interfaz
   web sigue funcionando).

3. **Arrancar el servidor**:

   ```bash
   uv run uvicorn app.main:app --reload
   ```

   Al arrancar se crean las tablas si no existen y se cargan los 3 modelos una sola
   vez.

4. **Crear el primer usuario** (no hay registro en la interfaz, a propósito): en
   `http://localhost:8000/docs` pulsa **Authorize**, pon la `API_KEY` y usa
   `POST /api/auth/register`.

5. **Entrar** en `http://localhost:8000/login` y cargar los reportes de ventas en la
   pestaña **Cargar ventas mensuales**. Se necesitan al menos 28 días de historial
   por producto para predecir.

| URL | Qué es |
|---|---|
| `/login` | Página de inicio de sesión (única pública) |
| `/inicio` | Aplicación (requiere sesión) |
| `/docs` | Documentación interactiva de la API |
| `/` | Health check: modelos cargados |

## API REST

Todas las rutas exigen el header `X-API-Key`.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/auth/register` | Crea un usuario (valida DNI, celular y fortaleza de la contraseña) |
| `POST` | `/api/auth/login` | Verifica usuario y contraseña |
| `POST` | `/api/prediccion/predecir` | Predicción de un día (incluye las 17 features usadas) |
| `POST` | `/api/prediccion/predecir-rango` | Predicción recursiva de 1–15 días |
| `POST` | `/api/prediccion/ingesta` | Carga un reporte mensual `.xlsx` |
| `GET` | `/api/prediccion/historial/{producto}` | Historial diario de ventas |
| `GET` | `/api/prediccion/metricas` | Métricas del modelo |

Ejemplo:

```bash
curl -X POST http://localhost:8000/api/prediccion/predecir \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"producto": "REGULAR", "fecha": "2026-10-15"}'
```

Errores esperables (producto no servido, fecha pasada, historial insuficiente o
fecha a más de 15 días del último dato) responden **422** con el motivo en
`detail`.

## Despliegue en Railway

`railway.json` arranca con:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Configura las mismas variables del `.env` en el servicio. Si la base también está
en Railway, usa su **host de red privada** (`*.railway.internal`) en `DB_HOST`: por
el proxy público cada consulta tarda bastante más.

## Notas

- Los `.joblib` se guardaron con scikit-learn 1.3.1 y se cargan con 1.9.x. El aviso
  de versión se silencia a propósito: `StandardScaler` + `Ridge` es aritmética
  estable entre versiones y reproduce las predicciones del notebook. No hace falta
  bajar de versión.
- BIODIESEL quedó fuera del sistema por decisión del modelado (ver notebooks); el
  ETL descarta sus filas al cargar los reportes.
