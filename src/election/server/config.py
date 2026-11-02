from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ELECTION_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: str = Field(repr=False)
    host: str = "127.0.0.1"
    port: int = 8443
    tls_cert: str = ".runtime/tls/server.pem"
    tls_key: str = ".runtime/tls/server-key.pem"

    @field_validator("database_url")
    @classmethod
    def require_mysql(cls, value: str) -> str:
        if not value.startswith("mysql+pymysql://"):
            raise ValueError("MySQL with PyMySQL is required")
        return value
