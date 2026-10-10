# Pathlib permite gestionar las rutas de los archivos
from pathlib import Path

# sirve para gestionar gestionar la configuración y las variables de entorno de la aplicación
from pydantic_settings import BaseSettings, SettingsConfigDict


# Artefactos de ML (modelos .joblib + config del servicio).
# La ruta se define aquí, junto al resto de la configuración.


# calcular la ruta absoluta hacia la carpeta "artefactos" que se encuentra dos niveles más arriba del archivo de Python actual.
ARTEFACTOS_DIR = Path(__file__).resolve().parent.parent / "artefactos"

MODELOS_DIR = ARTEFACTOS_DIR / "modelos"
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
