import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

from src.db.errors import MongoConnectionError

logger = logging.getLogger(__name__)


def create_mongo_client(uri: str) -> AsyncIOMotorClient[Any]:
    """Create an async Motor MongoDB client.

    Args:
        uri: MongoDB connection URI.

    Returns:
        An AsyncIOMotorClient instance.
    """
    logger.info("MongoDB client created for %s", uri)
    return AsyncIOMotorClient(uri)


async def check_mongo_health(client: AsyncIOMotorClient[Any]) -> bool:
    """Check MongoDB health by running a ping command.

    Args:
        client: An AsyncIOMotorClient instance.

    Returns:
        True if the ping succeeds with ok: 1.
    """
    try:
        result = await client.admin.command("ping")
        return result.get("ok") == 1.0
    except Exception as exc:
        logger.error("MongoDB health check failed: %s", exc)
        raise MongoConnectionError(f"MongoDB ping failed: {exc}") from exc


def close_mongo_client(client: AsyncIOMotorClient[Any]) -> None:
    """Close a MongoDB client connection.

    Args:
        client: An AsyncIOMotorClient instance to close.
    """
    client.close()
    logger.info("MongoDB client closed")
