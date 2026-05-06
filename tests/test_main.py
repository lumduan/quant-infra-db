import runpy
from unittest.mock import patch

from src.main import main


async def test_main_runs_without_error() -> None:
    """main() completes without raising an exception."""
    with (
        patch("src.main.Settings"),
        patch("src.main.create_postgres_pool"),
        patch("src.main.check_postgres_health"),
        patch("src.main.close_postgres_pool"),
        patch("src.main.create_mongo_client"),
        patch("src.main.check_mongo_health"),
        patch("src.main.close_mongo_client"),
    ):
        await main()


def test_main_as_entrypoint() -> None:
    """Cover the __name__ == '__main__' path."""
    with patch("asyncio.run"):
        runpy.run_module("src.main", run_name="__main__")
