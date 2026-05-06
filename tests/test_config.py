from unittest.mock import patch

import pytest
from pydantic import ValidationError
from src.config import Settings


class TestSettings:
    """Unit tests for Pydantic Settings model — no Docker required."""

    def test_default_hosts(self) -> None:
        """Default host and port values are localhost:5432/27017."""
        with patch.dict("os.environ", {"POSTGRES_PASSWORD": "test"}, clear=True):
            settings = Settings()
            assert settings.postgres_host == "localhost"
            assert settings.postgres_port == 5432
            assert settings.mongo_host == "localhost"
            assert settings.mongo_port == 27017

    def test_secret_str_not_exposed_in_repr(self) -> None:
        """repr() must not leak the password."""
        with patch.dict("os.environ", {"POSTGRES_PASSWORD": "s3cret"}, clear=True):
            settings = Settings()
            assert "s3cret" not in repr(settings)

    def test_frozen_settings_prevents_mutation(self) -> None:
        """Settings must be immutable (frozen=True)."""
        with patch.dict("os.environ", {"POSTGRES_PASSWORD": "test"}, clear=True):
            settings = Settings()
            with pytest.raises(ValidationError):
                settings.postgres_host = "other"

    def test_csm_set_dsn_format(self) -> None:
        """DSN string is correctly formatted for db_csm_set."""
        with patch.dict("os.environ", {"POSTGRES_PASSWORD": "mypass"}, clear=True):
            settings = Settings()
            dsn = settings.csm_set_dsn
            assert dsn == "postgresql://postgres:mypass@localhost:5432/db_csm_set"

    def test_gateway_dsn_format(self) -> None:
        """DSN string is correctly formatted for db_gateway."""
        with patch.dict("os.environ", {"POSTGRES_PASSWORD": "mypass"}, clear=True):
            settings = Settings()
            dsn = settings.gateway_dsn
            assert dsn == "postgresql://postgres:mypass@localhost:5432/db_gateway"

    def test_mongo_uri_format(self) -> None:
        """MongoDB URI is correctly formatted."""
        with patch.dict("os.environ", {"POSTGRES_PASSWORD": "test"}, clear=True):
            settings = Settings()
            assert settings.mongo_uri == "mongodb://localhost:27017"

    def test_custom_host_and_port(self) -> None:
        """DSNs reflect custom host and port overrides."""
        with patch.dict(
            "os.environ",
            {
                "POSTGRES_PASSWORD": "pwd",
                "POSTGRES_HOST": "quant-postgres",
                "POSTGRES_PORT": "6432",
                "MONGO_HOST": "quant-mongo",
                "MONGO_PORT": "27018",
            },
            clear=True,
        ):
            settings = Settings()
            assert settings.postgres_host == "quant-postgres"
            assert settings.postgres_port == 6432
            assert "quant-postgres:6432" in settings.csm_set_dsn
            assert settings.mongo_uri == "mongodb://quant-mongo:27018"
