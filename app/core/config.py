from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Artefactos de ML (modelos .joblib + config del servicio). Van en una ruta de
# artefactos separada, NO en app/models/ (que contiene modelos ORM). La ruta se
# define aquí, junto al resto de la configuración.
ARTEFACTOS_DIR = Path(__file__).resolve().parent.parent / "artefactos"
MODELOS_DIR = ARTEFACTOS_DIR / "modelos"
CONFIG_SERVICIO_PATH = ARTEFACTOS_DIR / "config_servicio.json"


class Settings(BaseSettings):
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    api_key: str | None = None

    debug: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://"
            f"{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}"
            f"/{self.db_name}"
        )


settings = Settings()
