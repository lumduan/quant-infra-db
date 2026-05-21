class DatabaseConnectionError(Exception):
    """Root exception for database connectivity failures."""


class PostgresConnectionError(DatabaseConnectionError):
    """PostgreSQL connection or query failure."""


class MongoConnectionError(DatabaseConnectionError):
    """MongoDB connection or query failure."""


class RepositoryError(DatabaseConnectionError):
    """Repository-layer failure (e.g. INSERT/UPDATE/SELECT against an asyncpg pool)."""
