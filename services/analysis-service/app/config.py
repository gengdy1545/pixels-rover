from functools import lru_cache
import json

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Pixels Rover"
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./rover.db"

    jwt_secret: str = "cGl4ZWxzZGItcm92ZXItand0LXNlY3JldC1rZXktMjAyNC1taW5pbXVtLTI1Ni1iaXRz"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "pixels-rover-auth-service"
    jwt_active_kid: str = "default-hmac"
    jwt_public_key_pem: str = ""
    jwt_public_keys_json: str = "{}"
    jwt_public_key_path: str = ""
    jwt_public_keys_path: str = ""
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

    def get_jwt_public_keys(self) -> dict[str, str]:
        public_keys: dict[str, str] = {}
        if self.jwt_public_keys_path:
            public_keys.update(json.loads(open(self.jwt_public_keys_path, "r", encoding="utf-8").read()))
        if self.jwt_public_keys_json:
            public_keys.update(json.loads(self.jwt_public_keys_json))
        if self.jwt_public_key_path:
            with open(self.jwt_public_key_path, "r", encoding="utf-8") as fp:
                public_keys[self.jwt_active_kid] = fp.read()
        if self.jwt_public_key_pem:
            public_keys[self.jwt_active_kid] = self.jwt_public_key_pem
        return public_keys


@lru_cache
def get_settings() -> Settings:
    return Settings()
