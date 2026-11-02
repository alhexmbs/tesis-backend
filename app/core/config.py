# Pathlib permite gestionar las rutas de los archivos
from pathlib import Path

# sirve para gestionar gestionar la configuración y las variables de entorno de la aplicación
from pydantic_settings import BaseSettings, SettingsConfigDict


# Artefactos de ML (modelos .joblib + config del servicio).
# La ruta se define aquí, junto al resto de la configuración.


# calcular la ruta absoluta hacia la carpeta "artefactos" que se encuentra dos niveles más arriba del archivo de Python actual.
ARTEFACTOS_DIR = Path(__file__).resolve().parent.parent / "artefactos"

MODELOS_DIR = ARTEFACTOS_DIR / "modelos"
VERIFICACION_PATH = ARTEFACTOS_DIR / "verificacion_septiembre.csv"
CONFIG_SERVICIO_PATH = ARTEFACTOS_DIR / "config_servicio.json"

# configuración de las variables de entorno de la base de datos
class Settings(BaseSettings):
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    api_key: str | None = None

    debug: bool = False

    # SOLO para desarrollo local: con true, /inicio se abre sin pedir login. Gradio
    # guarda las sesiones en memoria, así que cada reinicio del servidor (--reload)
    # obliga a autenticarse de nuevo. Nunca activarlo en Railway.
    ui_sin_login: bool = False

    # Recuperación de contraseña por correo (Resend). Sin RESEND_API_KEY la opción
    # "Olvidé mi contraseña" avisa que el envío no está configurado.
    resend_api_key: str | None = None
    # El remitente debe ser de un dominio verificado en Resend. onboarding@resend.dev
    # solo sirve para pruebas y entrega únicamente al correo dueño de la cuenta.
    correo_remitente: str = "BENZIN AI <onboarding@resend.dev>"
    # Dirección pública de la app, para armar el enlace del correo
    # (en Railway: https://<tu-app>.up.railway.app).
    url_publica: str = "http://localhost:8000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # permite acceder al valor como si fuera una variable normal, no como una función
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://"
            f"{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}"
            f"/{self.db_name}"
        )

# crea una instancia única en memoria para luego importar en el resto de la aplicación
settings = Settings()
