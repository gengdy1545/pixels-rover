from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_name: str = "Pixels Rover"
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./rover.db"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_api_base: str | None = None
    llm_temperature: float = 0.1
    llm_timeout: int = 60

    pixels_host: str = "localhost"
    pixels_port: int = 18890

    duckdb_path: str = ":memory:"

    default_max_steps: int = 10
    default_max_llm_calls: int = 20
    default_max_wall_time_sec: int = 180
    default_max_sql_executions: int = 5

    model_config = {"env_prefix": "ROVER_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
