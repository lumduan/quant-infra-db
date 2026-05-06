import logging

import asyncpg

from src.db.errors import PostgresConnectionError

logger = logging.getLogger(__name__)


async def create_postgres_pool(dsn: str) -> asyncpg.Pool:
    """Create an asyncpg connection pool for the given DSN.

    Args:
        dsn: PostgreSQL connection string.

    Returns:
        An asyncpg connection pool.

    Raises:
        PostgresConnectionError: If the pool cannot be created.
    """
    try:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
        logger.info("PostgreSQL pool created for %s", dsn.split("@")[-1])
        return pool
    except Exception as exc:
        raise PostgresConnectionError(f"Failed to create PostgreSQL pool: {exc}") from exc


async def check_postgres_health(pool: asyncpg.Pool) -> bool:
    """Check PostgreSQL health by running SELECT 1.

    Args:
        pool: An asyncpg connection pool.

    Returns:
        True if the query succeeds.
    """
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            return bool(result == 1)
    except Exception as exc:
        logger.error("PostgreSQL health check failed: %s", exc)
        return False


async def close_postgres_pool(pool: asyncpg.Pool) -> None:
    """Gracefully close a PostgreSQL connection pool.

    Args:
        pool: An asyncpg connection pool to close.
    """
    await pool.close()
    logger.info("PostgreSQL pool closed")
