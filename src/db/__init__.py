from src.db.errors import (
    DatabaseConnectionError,
    MongoConnectionError,
    PostgresConnectionError,
    RepositoryError,
)
from src.db.models import (
    BenchmarkEquityCurveRow,
    CorporateActionRow,
    OHLCVBarRow,
    StrategyReportSnapshotRow,
    TradeHistoryRow,
    UniverseMembershipRow,
)
from src.db.mongo import check_mongo_health, close_mongo_client, create_mongo_client
from src.db.postgres import check_postgres_health, close_postgres_pool, create_postgres_pool
from src.db.repositories import (
    fetch_benchmark_curve,
    fetch_ohlcv,
    fetch_strategy_report,
    fetch_trade_history,
    upsert_benchmark_equity,
    upsert_corporate_actions,
    upsert_ohlcv,
    upsert_strategy_report,
    upsert_trade_history,
    upsert_universe_membership,
)

__all__ = [
    "create_postgres_pool",
    "check_postgres_health",
    "close_postgres_pool",
    "create_mongo_client",
    "check_mongo_health",
    "close_mongo_client",
    "DatabaseConnectionError",
    "PostgresConnectionError",
    "MongoConnectionError",
    "RepositoryError",
    "TradeHistoryRow",
    "BenchmarkEquityCurveRow",
    "StrategyReportSnapshotRow",
    "OHLCVBarRow",
    "CorporateActionRow",
    "UniverseMembershipRow",
    "upsert_trade_history",
    "fetch_trade_history",
    "upsert_benchmark_equity",
    "fetch_benchmark_curve",
    "upsert_strategy_report",
    "fetch_strategy_report",
    "upsert_ohlcv",
    "fetch_ohlcv",
    "upsert_corporate_actions",
    "upsert_universe_membership",
]
