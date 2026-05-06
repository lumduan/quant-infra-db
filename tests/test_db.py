from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.db.errors import (
    DatabaseConnectionError,
    MongoConnectionError,
    PostgresConnectionError,
)
from src.db.mongo import check_mongo_health, close_mongo_client, create_mongo_client
from src.db.postgres import check_postgres_health, close_postgres_pool, create_postgres_pool


class TestErrors:
    """Unit tests for DB exception hierarchy."""

    def test_database_connection_error_is_exception(self) -> None:
        assert issubclass(DatabaseConnectionError, Exception)

    def test_postgres_connection_error_chain(self) -> None:
        assert issubclass(PostgresConnectionError, DatabaseConnectionError)

    def test_mongo_connection_error_chain(self) -> None:
        assert issubclass(MongoConnectionError, DatabaseConnectionError)


class TestPostgresPool:
    """Unit tests for PostgreSQL pool functions with mocked asyncpg."""

    @pytest.mark.asyncio
    async def test_create_postgres_pool_success(self) -> None:
        with patch("src.db.postgres.asyncpg.create_pool", new_callable=AsyncMock) as mock_create:
            mock_pool = MagicMock()
            mock_create.return_value = mock_pool
            result = await create_postgres_pool("postgresql://localhost:5432/db")
            assert result is mock_pool

    @pytest.mark.asyncio
    async def test_create_postgres_pool_failure(self) -> None:
        with (
            patch("src.db.postgres.asyncpg.create_pool", side_effect=OSError("boom")),
            pytest.raises(PostgresConnectionError, match="Failed to create PostgreSQL pool"),
        ):
            await create_postgres_pool("postgresql://bad:5432/db")

    @pytest.mark.asyncio
    async def test_check_postgres_health_healthy(self) -> None:
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        result = await check_postgres_health(mock_pool)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_postgres_health_unhealthy(self) -> None:
        mock_pool = MagicMock()
        mock_pool.acquire.side_effect = OSError("connection lost")
        result = await check_postgres_health(mock_pool)
        assert result is False

    @pytest.mark.asyncio
    async def test_close_postgres_pool(self) -> None:
        mock_pool = MagicMock()
        mock_pool.close = AsyncMock()
        await close_postgres_pool(mock_pool)
        mock_pool.close.assert_called_once()


class TestMongoClient:
    """Unit tests for MongoDB client functions with mocked motor."""

    def test_create_mongo_client(self) -> None:
        with patch("src.db.mongo.AsyncIOMotorClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            result = create_mongo_client("mongodb://localhost:27017")
            assert result is mock_client

    @pytest.mark.asyncio
    async def test_check_mongo_health_healthy(self) -> None:
        mock_client = MagicMock()
        mock_client.admin.command = AsyncMock(return_value={"ok": 1.0})
        result = await check_mongo_health(mock_client)
        assert result is True

    @pytest.mark.asyncio
    async def test_check_mongo_health_failure(self) -> None:
        mock_client = MagicMock()
        mock_client.admin.command = AsyncMock(side_effect=OSError("timeout"))
        with pytest.raises(MongoConnectionError, match="MongoDB ping failed"):
            await check_mongo_health(mock_client)

    def test_close_mongo_client(self) -> None:
        mock_client = MagicMock()
        close_mongo_client(mock_client)
        mock_client.close.assert_called_once()
