"""Data provider factory — switches between mock and akshare based on config.

All modules should use get_data_provider() instead of get_mock_provider() directly.
"""

from typing import Union
from config import settings
from src.infrastructure.mock_data_provider import MockDataProvider, get_mock_provider


DataProviderType = Union[MockDataProvider, "AKShareDataProvider"]


def get_data_provider() -> DataProviderType:
    """Get the configured data provider (mock or akshare)."""
    if settings.DATA_SOURCE == "akshare":
        from src.infrastructure.akshare_data_provider import get_akshare_provider
        return get_akshare_provider()
    else:
        return get_mock_provider()
