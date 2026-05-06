from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment and .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    # PostgreSQL
    postgres_password: SecretStr = SecretStr("")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"

    # MongoDB
    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_username: str = ""
    mongo_password: SecretStr = SecretStr("")
    mongo_database: str = "csm_logs"

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
        """Connection URI for MongoDB.

        Includes authentication credentials when mongo_username and
        mongo_password are both set.  Falls back to a no-auth URI otherwise
        (development without MONGO_INITDB_ROOT_USERNAME / MONGO_INITDB_ROOT_PASSWORD).
        """
        if self.mongo_username and self.mongo_password.get_secret_value():
            return (
                f"mongodb://{self.mongo_username}:"
                f"{self.mongo_password.get_secret_value()}"
                f"@{self.mongo_host}:{self.mongo_port}"
            )
        return f"mongodb://{self.mongo_host}:{self.mongo_port}"
