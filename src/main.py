import asyncio
import logging

from src.config import Settings
from src.db import (
    check_mongo_health,
    check_postgres_health,
    close_mongo_client,
    close_postgres_pool,
    create_mongo_client,
    create_postgres_pool,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    """Run connectivity smoke tests against PostgreSQL and MongoDB."""
    settings = Settings()

    # PostgreSQL — db_csm_set
    logger.info("Connecting to PostgreSQL (db_csm_set)...")
    csm_pool = await create_postgres_pool(settings.csm_set_dsn)
    csm_healthy = await check_postgres_health(csm_pool)
    logger.info("db_csm_set healthy: %s", csm_healthy)
    await close_postgres_pool(csm_pool)

    # PostgreSQL — db_gateway
    logger.info("Connecting to PostgreSQL (db_gateway)...")
    gw_pool = await create_postgres_pool(settings.gateway_dsn)
    gw_healthy = await check_postgres_health(gw_pool)
    logger.info("db_gateway healthy: %s", gw_healthy)
    await close_postgres_pool(gw_pool)

    # MongoDB
    logger.info("Connecting to MongoDB...")
    mongo_client = create_mongo_client(settings.mongo_uri)
    mongo_healthy = await check_mongo_health(mongo_client)
    logger.info("MongoDB healthy: %s", mongo_healthy)
    close_mongo_client(mongo_client)

    all_healthy = csm_healthy and gw_healthy and mongo_healthy
    if all_healthy:
        logger.info("All databases healthy — connectivity smoke test PASSED")
    else:
        logger.error("One or more databases are not healthy")
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(main())
