# Arquitectura de BENZIN AI (backend)

Diagramas Mermaid del proyecto. Se ven renderizados en VS Code (vista previa de
Markdown con la extensión *Markdown Preview Mermaid Support*), en GitHub y en
[mermaid.live](https://mermaid.live) pegando cada bloque.

1. [Capas y archivos](#1-capas-y-archivos)
2. [Predicción diaria paso a paso](#2-predicción-diaria-paso-a-paso)
3. [ETL: carga del reporte mensual](#3-etl-carga-del-reporte-mensual)
4. [Login y alta de usuarios](#4-login-y-alta-de-usuarios)
5. [Base de datos](#5-base-de-datos)
6. [Gradio: cómo se conecta un botón con Python](#6-gradio-cómo-se-conecta-un-botón-con-python)
7. [Plan de entregas (stock y capacidad del tanque)](#7-plan-de-entregas-stock-y-capacidad-del-tanque)
8. [Qué ve el usuario y qué no](#8-qué-ve-el-usuario-y-qué-no)

---

## 1. Capas y archivos

Todo corre en un solo proceso FastAPI (`app/main.py`). Hay **dos puertas de
entrada** que llegan a los **mismos servicios**: la UI Gradio (para el encargado del
grifo) y la API REST (para un frontend externo, p. ej. Angular).

```mermaid
flowchart TB
    usuario(["👤 Navegador"])

    subgraph MAIN["app/main.py — FastAPI"]
        direction TB
        lifespan["lifespan()<br/>carga modelos al arrancar"]
        mount["gr.mount_gradio_app()<br/>/login · /inicio"]
        routers["include_router()<br/>/api/auth · /api/prediccion"]
    end

    subgraph UI["app/ui — interfaz Gradio"]
        direction TB
        paginas["paginas/<br/>login.py · inicio.py"]
        comp["componentes.py<br/>banner, error_html, leer_js"]
        uiauth["auth.py<br/>autenticar()"]
        static["static/<br/>estilos.css · js/*.js"]
    end

    subgraph API["app/routers — API REST"]
        direction TB
        rauth["auth.py<br/>POST /login · /register"]
        rpred["prediccion.py<br/>/predecir · /predecir-rango<br/>/ingesta · /historial · /metricas"]
        schemas["app/schemas<br/>validan JSON (Pydantic)"]
    end

    subgraph SERV["app/services — lógica de negocio"]
        direction TB
        sauth["auth.py<br/>register_service · login_service"]
        spred["prediccion/servicio.py<br/>predecir_dia · predecir_rango<br/>metricas_modelo · venta_promedio_diaria"]
        etl["prediccion/ingesta.py<br/>extraccion.py · agregacion.py"]
        feat["prediccion/features.py<br/>17 features + base_28"]
        clima["prediccion/clima.py<br/>temperatura (Open-Meteo)<br/>en memoria 1 hora"]
        entregas["entregas.py<br/>planificar_entregas<br/>(no usa el modelo)"]
    end

    subgraph UTIL["app/utils"]
        valid["validaciones.py"]
        pwd["password.py<br/>hash + fuerza (zxcvbn)"]
    end

    subgraph DATOS["Datos"]
        db[("PostgreSQL<br/>usuarios · historial_ventas")]
        art[/"app/artefactos<br/>modelos/*.joblib<br/>config_servicio.json"/]
        meteo{{"api.open-meteo.com"}}
    end

    usuario --> mount
    usuario -. "JSON" .-> routers
    mount --> paginas
    paginas --> comp --> static
    mount --> uiauth
    routers --> rauth & rpred
    rauth & rpred --> schemas

    paginas --> sauth & spred & etl & entregas
    uiauth --> sauth
    rauth --> sauth
    rpred --> spred & etl

    sauth --> valid & pwd
    spred --> feat & clima
    sauth & spred & etl --> db
    lifespan --> art
    spred --> art
    clima --> meteo
```

**Idea clave para explicar:** la UI y la API son solo "caras". Toda la lógica
está en `services/`, por eso un cambio en cómo se predice afecta a las dos a la vez.

---

## 2. Predicción diaria paso a paso

Qué pasa cuando el usuario elige producto + fecha y aprieta **Predecir**.

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant UI as inicio.py<br/>predecir_ui
    participant EJ as inicio.py<br/>_ejecutar
    participant S as servicio.py<br/>predecir_dia
    participant DB as PostgreSQL<br/>historial_ventas
    participant C as clima.py
    participant F as features.py
    participant M as Modelo Ridge<br/>PRODUCTO.joblib

    U->>UI: clic "Predecir" (producto, "2026-10-01")
    UI->>EJ: _ejecutar(predecir_dia, producto, fecha_str)
    EJ->>EJ: validar_fecha() → date<br/>(si falla: "Fecha inválida")
    EJ->>S: predecir_dia(db, producto, fecha)
    S->>S: ¿producto servido? ¿fecha ≥ hoy?
    S->>DB: historial del producto
    DB-->>S: filas diarias (cantidad, precio, …)
    S->>S: ¿el hueco hasta la fecha ≤ 15 días?
    S->>C: obtener_temperatura_max(fecha)
    opt La memoria del clima venció (más de 1 hora)
        C->>C: 1 sola petición a Open-Meteo<br/>(31 días atrás + 16 adelante)
    end
    C-->>S: °C (pronóstico o promedio del mes)

    opt Hay días sin cargar entre el último real y la fecha
        loop por cada día del hueco (_puentear_historial)
            S->>F: features del día
            S->>M: predict → galones estimados
            S->>S: añade el día estimado al historial
        end
    end

    S->>F: calcular_features_dia(historial, fecha, temp)
    F-->>S: 17 features + base_28 (media 28 días previos)
    S->>M: predict(features) → razón
    M-->>S: razón (p. ej. 1.08)
    S->>S: galones = razón × base_28
    S-->>EJ: dict (galones, base_28, precio, notas…)
    EJ-->>UI: (resultado, None)
    UI-->>U: banner verde con la cifra
```

**Lo que más preguntan:**

- **¿Qué predice el modelo?** No galones directos: predice la **razón** frente
  al promedio de los 28 días anteriores (`base_28`). Los galones salen de
  `razón × base_28` (`servicio.py`, `_predecir`).
- **¿Por qué 28 días mínimo?** Sin ellos no existe `base_28` → `HistorialInsuficiente`.
- **¿Qué es el "puente"?** El reporte llega mensual; los días sin cargar se
  estiman con el propio modelo (máx. `MAX_HORIZONTE_DIAS = 15`) en vez de
  tratarlos como ceros.
- **Predicción de rango** = el mismo proceso en bucle, un día tras otro, usando
  cada predicción como historial del siguiente.
- **¿Por qué es rápida?** Antes `clima.py` hacía una petición HTTP **por día**
  (~0.7 s cada una): con 10 días de puente eran ~7 s. Ahora una sola petición trae
  47 días y queda en memoria 1 hora (`_temperaturas`, protegida con un `Lock`
  porque Gradio atiende varias peticiones a la vez). Los valores son los mismos que
  día por día. Si Open-Meteo falla, se usa el promedio del mes durante 5 minutos y
  luego se reintenta (antes cada día podía esperar 10 s de timeout).
- **Lo que aún tarda** es la base de datos si se usa el proxy público de Railway
  (~0.35 s por consulta). Desplegado en Railway con la red privada es mucho menor.

---

## 3. ETL: carga del reporte mensual

Única forma en que entran ventas al sistema.

```mermaid
flowchart LR
    xlsx[/"📄 Reporte mensual .xlsx<br/>(sistema del grifo)"/]

    subgraph E["Extract — extraccion.py"]
        e1["extraer_excel()<br/>lee con pandas<br/>verifica columnas requeridas"]
    end

    subgraph T["Transform — agregacion.py + ingesta.py"]
        direction TB
        t1["limpiar_datos()<br/>código artículo → producto<br/>agrupa por día × producto"]
        t2["filtra REGULAR · PREMIUM · GLP<br/>(BIODIESEL se descarta)"]
        t3["días sin ventas → cantidad 0<br/>precio: arrastre (ffill)<br/>desde el lote o la BD"]
        t4["sin precio posible → se omite"]
        t1 --> t2 --> t3 --> t4
    end

    subgraph L["Load — ingesta.py"]
        l1["UPSERT por (fecha, producto)<br/>existe → actualiza<br/>no existe → inserta"]
        l2["db.commit()"]
        l1 --> l2
    end

    db[("historial_ventas")]

    xlsx --> e1 --> t1
    t4 --> l1
    l2 --> db
```

Entradas al ETL:

- **UI:** pestaña "Cargar ventas mensuales" → `cargar_xlsx_ui` → `ingerir_ventas_mensuales`
  (archivos ordenados por nombre para que los meses entren en orden).
- **API:** `POST /api/prediccion/ingesta`.

**Idempotente** = subir el mismo mes dos veces no duplica filas, las actualiza
(gracias al `UniqueConstraint(fecha, producto)` + el upsert).

---

## 4. Login y alta de usuarios

```mermaid
sequenceDiagram
    autonumber
    actor U as Usuario
    participant API as POST /api/auth/register
    participant L as login.js<br/>(navegador)
    participant G as Gradio auth<br/>/inicio/login
    participant A as ui/auth.py<br/>autenticar
    participant S as services/auth.py
    participant P as utils/password.py
    participant DB as usuarios

    Note over U,DB: Alta de usuario (solo el administrador, por API)
    U->>API: JSON con nombres, apellidos, DNI, celular, usuario, contraseña
    API->>S: register_service(...)
    S->>S: validar_datos_registro (DNI, celular, nombres…)
    S->>P: validate_password_strength (zxcvbn)
    S->>DB: ¿username / DNI / celular ya existen?
    S->>P: hash_password (pwdlib)
    S->>DB: INSERT usuario (contraseña hasheada)
    API-->>U: 200 usuario creado · 400 dato inválido · 409 duplicado

    Note over U,DB: Login
    U->>L: usuario + contraseña → "Iniciar sesión"
    L->>G: fetch POST /inicio/login
    G->>A: autenticar(username, password)
    A->>S: login_service
    S->>DB: SELECT por username
    S->>P: verify_password(texto, hash)
    A-->>G: True / False
    G-->>L: 200 → redirige a /inicio<br/>401 → "Usuario o contraseña incorrectos"
```

La UI **no** tiene página de registro: el sistema es solo para el administrador del
grifo y un formulario público dejaría a cualquiera con el enlace crear cuenta y ver
las predicciones. Las cuentas se crean con `POST /api/auth/register`.

Toda la API REST (`/api/auth/*` y `/api/prediccion/*`) exige el header `X-API-Key`
con el valor de la variable `API_KEY` (`app/core/seguridad.py`, aplicado en
`include_router` de `main.py`). Sin la clave responde 401; si el servidor no tiene
`API_KEY` configurada responde 503, así nunca queda abierta por olvido. En `/docs` se
pone con el botón **Authorize**. La UI de Gradio no usa estas rutas (llama a los
servicios directo), así que el login y `/inicio` funcionan igual.

**Bloqueo por intentos fallidos** (`ui/auth.py`): tras 5 contraseñas erradas
seguidas, ese usuario queda bloqueado 15 minutos aunque luego acierte. Es por usuario
(Gradio no le pasa la IP a `autenticar`) y vive en memoria: reiniciar el servidor lo
limpia. El mensaje de error es el mismo para clave errada y bloqueo.

La contraseña **nunca** se guarda en texto plano: solo el hash. Al iniciar
sesión se compara con `verify_password`.

---

## 5. Base de datos

Solo dos tablas, sin relación entre sí. Se crean al arrancar con
`Base.metadata.create_all` (`main.py`).

```mermaid
erDiagram
    USUARIOS {
        int id PK
        string nombres
        string apellidos
        string dni UK
        string nro_celular UK
        string username UK
        string password "hash, no texto plano"
        datetime fecha_creacion
        bool estado
    }

    HISTORIAL_VENTAS {
        int id PK
        date fecha "UK junto con producto"
        string producto "REGULAR | PREMIUM | GLP"
        numeric cantidad "galones del día"
        numeric precio_promedio "S/ por galón"
        int n_transacciones_totales
        numeric proporcion_transacciones_grandes
    }
```

`historial_ventas` guarda datos **crudos** diarios, no features. Las 17 features
se recalculan en cada predicción → si cambia la definición de una feature, no hay
que recargar datos.

---

## 6. Gradio: cómo se conecta un botón con Python

Patrón que se repite en todas las páginas. Ejemplo real de `inicio.py`
(predicción de rango):

```mermaid
flowchart LR
    subgraph IN["inputs=[...] (en orden)"]
        i1["r_producto<br/>Dropdown"]
        i2["r_fecha<br/>calendario (HTML)"]
        i3["r_dias<br/>Slider"]
        i4["r_stock<br/>Number"]
        i5["r_capacidad<br/>Number"]
        i6["r_llenado<br/>Slider"]
        i7["r_minimo<br/>Number"]
    end

    fn["predecir_rango_ui(<br/>producto,<br/>fecha_inicio_str,<br/>dias,<br/>stock,<br/>capacidad,<br/>llenado_max,<br/>stock_minimo)<br/><br/>return tabla, resumen, detalle"]

    subgraph OUT["outputs=[...] (en orden)"]
        o1["r_grafico<br/>LinePlot"]
        o2["r_resumen<br/>HTML"]
        o3["r_tabla<br/>Dataframe"]
    end

    boton(["r_boton.click"]) --> fn
    i1 -- "1.er parámetro" --> fn
    i2 -- "2.º parámetro" --> fn
    i3 -- "3.er parámetro" --> fn
    i4 & i5 & i6 & i7 -- "4.º a 7.º parámetro" --> fn
    fn -- "1.er valor" --> o1
    fn -- "2.º valor" --> o2
    fn -- "3.er valor" --> o3
```

Regla: **cada componente de `inputs` entra como parámetro, en orden; cada valor
del `return` va al componente de `outputs`, en orden.** Si agregas un output,
la función tiene que devolver un valor más.

Otro evento del mismo patrón: al salir de un campo de galones (`.blur`), se llama a
`galones_validos` con ese campo como input **y** como output, así un `-5` o un campo
vacío vuelve a `0` en pantalla. No se usa `minimum=0` de Gradio porque deja escribir
el negativo igual y recién al predecir lanza un error en inglés.

---

## 7. Plan de entregas (stock y capacidad del tanque)

Responde **qué día recibir combustible y cuánto**, en la pestaña de rango. Vive en
`app/services/entregas.py`: no usa Gradio ni el modelo, solo recibe la venta
estimada de cada día (`predecir_rango`) y simula el tanque.

```mermaid
flowchart TB
    ini(["stock = stock inicial<br/>tope = capacidad × llenado %"])
    val{"¿datos posibles?<br/>stock ≤ capacidad<br/>mínimo < tope<br/>venta del día ≤ tope − mínimo"}
    err["PlanImposible<br/>aviso en español"]
    dia["siguiente día del rango"]
    q{"¿stock − venta<br/>queda bajo el mínimo?"}
    ent["ENTREGA antes de abrir<br/>entrega = tope − stock<br/>stock = tope"]
    vende["stock = stock − venta"]
    fin(["entregas · total pedido<br/>stock final"])

    ini --> val
    val -- no --> err
    val -- sí --> dia --> q
    q -- sí --> ent --> vende
    q -- no --> vende
    vende -- "quedan días" --> dia
    vende -- "último día" --> fin
```

Ejemplo (venta de ~71 gal/día, stock 100, tanque de 300 al 100 %): entrega de 271
el día 2 y de 286 el día 6; el tanque cierra la semana con 157.

- **Sin capacidad (0):** no hay plan; se sugiere un solo pedido = venta − stock, más
  una versión "con colchón" que suma el error típico del modelo (MAPE).
- **Llenar el tanque en cada entrega** = menos entregas (menos fletes).
- **Llenado máximo** (por defecto 95 %): los tanques no se llenan al 100 % porque
  el combustible se dilata (el GLP, ≈ 85 %).
- **Stock mínimo:** reserva que nunca se toca; cubre errores del modelo y demoras.
- **Supuesto:** la entrega llega el mismo día, antes de abrir. No se modelan días
  de anticipación del proveedor ni tamaños fijos de cisterna.
- La tabla "Detalle" muestra por día: stock al abrir, entrega, venta estimada y
  stock al cerrar.

---

## 8. Qué ve el usuario y qué no

La UI es para el encargado o el contador del grifo, no para un estadístico.

| Dato | ¿Lo usa el modelo? | ¿Se muestra? | Por qué |
|---|---|---|---|
| Temperatura máxima | sí (feature) | **no** | No sirve para decidir nada y confunde ("¿qué tiene que ver el clima?"). Sigue en la respuesta de la API. |
| 17 features (lags, razones…) | sí | no | Solo en la API, para trazabilidad. |
| Venta diaria promedio del último mes (`base_28`) | sí | sí | Da escala a la cifra predicha. |
| Precio de referencia | sí (congelado) | sí | Contexto. |

**Pestaña de métricas, en lenguaje llano** (`cargar_metricas_ui`):

- El error en galones va **junto a la venta diaria** del producto
  (`venta_promedio_diaria`, últimos 90 días hasta la fecha de entrenamiento) y en %:
  138 galones de error en GLP asustan, pero sobre ~2,900 gal/día son < 5 %.
- En vez de MASE se compara con el **método simple**: repetir lo vendido el mismo
  día de la semana pasada (naive estacional). `metricas_modelo` calcula
  `mejora_vs_simple_pct = (1 − MAE_modelo / MAE_naive) × 100` con los números de
  `config_servicio.json`: REGULAR 21 %, PREMIUM 34 %, GLP 15 % menos error.
- **¿Cómo sé que el modelo acierta en el futuro?** Además de estos 90 días de
  holdout, el notebook `backtesting.ipynb` simula 38 meses pasados como si fueran
  futuro, reentrenando cada mes. Su escenario S3 (bloque ciego, recursivo) es
  exactamente lo que hace la predicción de rango.
