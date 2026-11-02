# Gestión de riesgos y evaluación de amenazas — BENZIN AI

## 1. Objetivo y alcance

Identificar los riesgos que pueden afectar a BENZIN AI (sistema de predicción de
demanda de combustible para el área de administración de un grifo), evaluar su
probabilidad e impacto y documentar los controles implementados en el sistema y las
acciones pendientes.

Alcance: aplicación web (interfaz Gradio + API REST FastAPI), base de datos
PostgreSQL, modelos de predicción, servicio externo de clima (Open-Meteo) y
despliegue en Railway.

## 2. Metodología

Cada riesgo se evalúa antes de aplicar controles (riesgo inherente):

| Valor | Probabilidad | Impacto |
|---|---|---|
| 1 | Baja: poco probable en un año de uso | Bajo: molestia menor, sin pérdida de datos ni decisiones erradas |
| 2 | Media: puede ocurrir algunas veces al año | Medio: interrumpe una tarea o afecta una decisión de compra |
| 3 | Alta: puede ocurrir con frecuencia | Alto: pérdida de datos, acceso indebido o desabastecimiento |

**Nivel = Probabilidad × Impacto** → 1–2 **Bajo** · 3–4 **Medio** · 6–9 **Alto**.

El **riesgo residual** es el nivel que queda después de los controles ya implementados.

## 3. Matriz resumen

| ID | Riesgo | P | I | Nivel inherente | Residual |
|---|---|---|---|---|---|
| R01 | Adivinación o robo de contraseña | 2 | 3 | Alto (6) | Bajo |
| R02 | Bloqueo malintencionado de una cuenta | 1 | 2 | Bajo (2) | Bajo |
| R03 | Cuenta compartida con terceros | 2 | 2 | Medio (4) | Medio |
| R04 | Acceso no autorizado a la API REST | 2 | 3 | Alto (6) | Bajo |
| R05 | Filtración de credenciales del servidor | 1 | 3 | Medio (3) | Bajo |
| R06 | Desactivar el login por error en producción | 1 | 3 | Medio (3) | Bajo |
| R07 | Carga de un archivo malicioso o muy pesado | 1 | 2 | Bajo (2) | Bajo |
| R08 | Reporte de ventas con errores o formato distinto | 3 | 2 | Alto (6) | Bajo |
| R09 | Datos duplicados al subir dos veces un mes | 3 | 2 | Alto (6) | Bajo |
| R10 | Pérdida de la base de datos | 1 | 3 | Medio (3) | Medio |
| R11 | Caída de la conexión con la base de datos | 3 | 2 | Alto (6) | Bajo |
| R12 | Falla del servicio de clima (Open-Meteo) | 2 | 1 | Bajo (2) | Bajo |
| R13 | Reinicio o caída del servidor | 2 | 2 | Medio (4) | Bajo |
| R14 | Error de predicción mayor al esperado | 2 | 3 | Alto (6) | Medio |
| R15 | Ventas desactualizadas (reporte atrasado) | 3 | 2 | Alto (6) | Bajo |
| R16 | Cambio en el comportamiento de la demanda | 2 | 3 | Alto (6) | Medio |
| R17 | Datos del tanque ingresados con error | 3 | 2 | Alto (6) | Bajo |
| R18 | Hora de pago vencida o desabastecimiento del proveedor | 2 | 3 | Alto (6) | Medio |
| R19 | Demanda diaria mayor que el tanque o el camión | 1 | 2 | Bajo (2) | Bajo |

## 4. Detalle por riesgo

### 4.1 Seguridad

**R01 — Adivinación o robo de contraseña**
- *Escenario:* un tercero prueba contraseñas (fuerza bruta) o usa una contraseña débil.
- *Controles implementados:*
  - Contraseñas guardadas con hash (`pwdlib`, algoritmo recomendado), nunca en texto plano.
  - Fortaleza mínima con `zxcvbn` (puntaje ≥ 3, 8 a 128 caracteres) y prohibición de usar datos personales (nombres, DNI, celular, usuario).
  - Bloqueo de la cuenta por 15 minutos tras 5 intentos fallidos seguidos.
  - Mensaje único "Usuario o contraseña incorrectos": no revela si el usuario existe.
  - Cambio de contraseña obligatorio en el primer ingreso: ni el administrador que creó la cuenta conoce la contraseña final.
  - Conexión cifrada (HTTPS) provista por Railway.
  - Recuperación por correo ("¿Olvidaste tu contraseña?"): enlace de un solo uso que vence en 30 minutos; en la base solo se guarda su hash; el mensaje en pantalla es el mismo exista o no el correo; como máximo un envío por minuto por cuenta; el correo indica que, si el usuario no lo pidió, no haga nada.
- *Residual / acción:* el contador de intentos vive en memoria y se reinicia si el servidor se reinicia. Aceptable para un solo grifo.

**R02 — Bloqueo malintencionado de una cuenta**
- *Escenario:* alguien que conoce el nombre de usuario falla 5 veces a propósito para bloquearlo.
- *Controles:* el bloqueo dura solo 15 minutos y el sistema es de uso interno (pocas personas conocen la dirección y los usuarios).
- *Residual:* bajo. Se acepta.

**R03 — Cuenta compartida con terceros**
- *Escenario:* el administrador presta su cuenta.
- *Controles:* cada cuenta es nominativa (nombres, DNI y celular únicos); el sistema cuenta los inicios de sesión de cada cuenta; el uso de la cuenta es responsabilidad del titular (política del manual de usuario).
- *Residual / acción:* no hay bitácora de acciones por usuario. Se recomienda agregarla si el sistema pasa a tener varios usuarios.

**R04 — Acceso no autorizado a la API REST**
- *Escenario:* alguien llama directamente a `/api/...` para crear cuentas, ver predicciones o sobrescribir ventas.
- *Controles:* todas las rutas exigen la cabecera `X-API-Key`; la clave se compara en tiempo constante (`secrets.compare_digest`); si la clave no está configurada, la API se cierra (503) en lugar de quedar abierta; no existe registro público de cuentas.
- *Residual / acción:* CORS permite cualquier origen (`*`). Restringirlo al dominio del front-end cuando exista.

**R05 — Filtración de credenciales del servidor**
- *Escenario:* se publican la contraseña de la base de datos o la clave de la API.
- *Controles:* las credenciales están en variables de entorno (`.env` local, variables de Railway); `.env` está excluido del repositorio (`.gitignore`).
- *Acción ante incidente:* cambiar la contraseña de la base y la `API_KEY` en Railway.

**R06 — Desactivar el login por error en producción**
- *Escenario:* la opción de desarrollo `UI_SIN_LOGIN` queda activa en Railway y cualquiera entra sin contraseña.
- *Controles:* está apagada por defecto; si se activa, el servidor registra una advertencia al arrancar; solo se lee del `.env` local, que no se sube al repositorio.
- *Acción:* revisar las variables de Railway antes de cada despliegue.

**R07 — Carga de un archivo malicioso o muy pesado**
- *Escenario:* se sube un archivo que no es un reporte de ventas o uno muy grande.
- *Controles:* solo se aceptan `.xlsx`/`.xls`; se verifican las columnas requeridas; un archivo inválido muestra un error y no detiene la carga de los demás; la carga solo está disponible para usuarios autenticados.
- *Acción:* definir un tamaño máximo de archivo.

### 4.2 Datos

**R08 — Reporte de ventas con errores o formato distinto**
- *Escenario:* el sistema del grifo cambia el formato del reporte, o el archivo trae filas incompletas.
- *Controles:* validación de columnas antes de procesar; solo se guardan REGULAR, PREMIUM y GLP; las notas de crédito restan; un día con saldo negativo se guarda como 0; los días sin precio previo se omiten y se informan; mensajes claros por archivo.
- *Residual:* bajo.

**R09 — Datos duplicados o modificados al subir dos veces un mes**
- *Controles:* si el archivo trae alguna fecha ya registrada, se rechaza entero y no se guarda nada; el mensaje indica contactar al administrador si el reporte tiene correcciones. El reporte llega revisado por el área contable.
- *Residual:* bajo.

**R10 — Pérdida de la base de datos**
- *Escenario:* falla del proveedor o borrado accidental.
- *Controles:* base PostgreSQL administrada en Railway; los reportes mensuales originales (`.xlsx`) permiten reconstruir el historial volviéndolos a cargar.
- *Acción:* programar copias de seguridad periódicas de la base.

### 4.3 Disponibilidad

**R11 — Caída de la conexión con la base de datos**
- *Escenario:* Railway cierra conexiones inactivas y la siguiente consulta falla ("SSL error: unexpected eof while reading").
- *Controles:* `pool_pre_ping` comprueba cada conexión antes de usarla y abre otra si está caída; `pool_recycle` renueva las conexiones cada 5 minutos. El usuario no ve el error.

**R12 — Falla del servicio de clima (Open-Meteo)**
- *Controles:* tiempo de espera de 10 s; si falla, se usa la temperatura máxima promedio del mes (respaldo histórico) y la predicción continúa; tras un fallo no se reintenta durante 5 minutos; el pronóstico se guarda en memoria por 1 hora.

**R13 — Reinicio o caída del servidor**
- *Controles:* Railway reinicia el servicio; los datos están en PostgreSQL y no se pierden; los modelos se vuelven a cargar al arrancar.
- *Residual:* las sesiones abiertas se pierden y el usuario debe iniciar sesión de nuevo.

### 4.4 Modelo y predicción

**R14 — Error de predicción mayor al esperado**
- *Escenario:* la venta real se aleja de la estimada y se pide de menos o de más.
- *Controles:* el error se midió con una prueba fuera de muestra (septiembre 2026, modelo entrenado hasta agosto). El margen de error por día se muestra en galones (percentil 90): GLP ±204, REGULAR ±135, PREMIUM ±119 gal. El plan mantiene una reserva mínima del 15 % del tanque. En la prueba el modelo tendió a sobrestimar (lado seguro).
- *Residual / acción:* medio. La prueba cubre un solo mes; ampliarla a medida que haya más datos.

**R15 — Ventas desactualizadas (reporte atrasado)**
- *Controles:* los días sin reporte se estiman con el propio modelo (puente recursivo) y se avisa al usuario; la proyección se limita a 15 días desde el último día con ventas; el calendario no permite fechas fuera de ese rango; el aviso incluye un botón para cargar ventas.

**R16 — Cambio en el comportamiento de la demanda**
- *Escenario:* nuevo competidor, cambio fuerte de precios u otro evento que el historial no contiene.
- *Controles:* la pestaña "Métricas del modelo" compara lo real con lo predicho.
- *Acción:* reentrenar el modelo periódicamente con el historial actualizado. El modelo no simula escenarios de precio (el precio entra congelado).

### 4.5 Operación

**R17 — Datos del tanque ingresados con error**
- *Controles:* los campos de galones actuales y capacidad son obligatorios y el botón "Predecir" queda deshabilitado sin ellos; un valor negativo se corrige a 0; si los galones actuales superan la capacidad (o, en GLP, el límite de llenado del 80 %), se muestra un error y no se predice.

**R18 — Hora de pago vencida o desabastecimiento del proveedor**
- *Escenario:* se consulta después de la hora límite de pago (15:00 del día anterior) o el proveedor no despacha (por ejemplo, cierre de puerto por oleaje).
- *Controles:* el sistema marca los días cuyo pedido ya no llega a tiempo, indica cuándo llegaría el combustible si se paga ahora y recomienda llamar al proveedor.
- *Residual:* medio. Los cortes de abastecimiento del proveedor no se modelan; se cubren con la reserva mínima y con la estimación de demanda de los días siguientes.

**R19 — Demanda diaria mayor que el tanque o el camión**
- *Controles:* si la venta estimada de un día supera lo que el tanque puede entregar o lo que trae un camión (GLP 6 500 gal, líquidos 4 380 gal), el sistema lo informa en lugar de armar un plan imposible.

## 5. Acciones pendientes (priorizadas)

| Prioridad | Acción | Riesgo |
|---|---|---|
| 1 | Programar copias de seguridad de la base de datos | R10 |
| 2 | Reentrenar el modelo y ampliar la prueba real vs. predicho cada mes | R14, R16 |
| 3 | Revisar variables de Railway en cada despliegue (`UI_SIN_LOGIN`, `API_KEY`) | R05, R06 |
| 4 | Restringir CORS al dominio del front-end | R04 |
| 5 | Limitar el tamaño de los archivos de ventas | R07 |
| 6 | Bitácora de acciones por usuario, si el sistema pasa a tener varios usuarios | R03 |
