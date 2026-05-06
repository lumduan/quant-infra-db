from typing import Any

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from src.config import Settings

pytestmark = pytest.mark.infra


@pytest.fixture
def settings() -> Settings:
    """Load settings from .env."""
    return Settings()


@pytest.fixture
def mongo_client(settings: Settings) -> AsyncIOMotorClient[Any]:
    """Create an async MongoDB client."""
    return AsyncIOMotorClient[Any](settings.mongo_uri)


async def test_connect_and_ping(mongo_client: AsyncIOMotorClient[Any]) -> None:
    """Ping command returns ok: 1."""
    result = await mongo_client.admin.command("ping")
    assert result["ok"] == 1.0


async def test_collections_exist(mongo_client: AsyncIOMotorClient[Any]) -> None:
    """csm_logs database has the expected collections."""
    db = mongo_client.csm_logs
    names = await db.list_collection_names()
    assert "backtest_results" in names
    assert "model_params" in names
    assert "signal_snapshots" in names


async def test_indexes_exist(mongo_client: AsyncIOMotorClient[Any]) -> None:
    """backtest_results has the expected compound index."""
    db = mongo_client.csm_logs
    indexes = await db.backtest_results.index_information()
    # The _id index is always present; check for our compound index
    index_keys = [v["key"] for v in indexes.values()]
    expected = [("strategy_id", 1), ("created_at", -1)]
    assert expected in index_keys


async def test_document_round_trip(mongo_client: AsyncIOMotorClient[Any]) -> None:
    """Insert a document, read it back, delete it."""
    db = mongo_client.csm_logs
    doc = {"strategy_id": "test_strategy", "created_at": "2026-05-06T00:00:00Z", "value": 42}
    result = await db.backtest_results.insert_one(doc)
    assert result.inserted_id is not None

    found = await db.backtest_results.find_one({"strategy_id": "test_strategy"})
    assert found is not None
    assert found["value"] == 42

    await db.backtest_results.delete_one({"strategy_id": "test_strategy"})
    count = await db.backtest_results.count_documents({"strategy_id": "test_strategy"})
    assert count == 0
