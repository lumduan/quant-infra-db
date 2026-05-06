from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment and .env file."""

    model_config = SettingsConfigDict(env_file=".env", frozen=True)

    # PostgreSQL
    postgres_password: SecretStr = SecretStr("")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"

    # MongoDB
    mongo_host: str = "localhost"
    mongo_port: int = 27017

    @field_validator("postgres_password")
    @classmethod
    def password_must_be_set(cls, v: SecretStr) -> SecretStr:
        """Ensure the password is not empty at runtime."""
        if not v.get_secret_value():
            raise ValueError("POSTGRES_PASSWORD environment variable must be set")
        return v

    @property
    def csm_set_dsn(self) -> str:
        """Connection string for the db_csm_set database."""
        return (
            f"postgresql://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/db_csm_set"
        )

    @property
    def gateway_dsn(self) -> str:
        """Connection string for the db_gateway database."""
        return (
            f"postgresql://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/db_gateway"
        )

    @property
    def mongo_uri(self) -> str:
        """Connection URI for MongoDB."""
        return f"mongodb://{self.mongo_host}:{self.mongo_port}"
