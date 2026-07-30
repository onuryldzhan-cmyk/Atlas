from __future__ import annotations

from unittest.mock import patch

from atlas_finance.market_data.binance_public_provider import (
    BinancePublicDataProvider,
)


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.close_count = 0

    def close(self) -> None:
        self.closed = True
        self.close_count += 1


def test_owned_provider_can_restart_after_disconnect() -> None:
    """
    Verify connect -> disconnect -> connect without network access.
    """

    first_session = FakeSession()
    second_session = FakeSession()

    provider = BinancePublicDataProvider(
        session=first_session,
    )

    # Simulate a session created and owned internally by the provider.
    provider._owns_session = True
    provider.get_price = lambda symbol: object()

    assert provider.connect() is True
    assert provider.connected is True

    provider.disconnect()

    assert provider.connected is False
    assert first_session.closed is True
    assert first_session.close_count == 1

    with patch(
        "atlas_finance.market_data.binance_public_provider."
        "requests.Session",
        return_value=second_session,
    ) as session_factory:
        assert provider.connect() is True

    session_factory.assert_called_once_with()

    assert provider.connected is True
    assert provider._session is second_session
    assert provider._closed is False

    provider.disconnect()

    assert provider.connected is False
    assert second_session.closed is True
    assert second_session.close_count == 1


def test_disconnect_is_idempotent_for_owned_session() -> None:
    session = FakeSession()

    provider = BinancePublicDataProvider(
        session=session,
    )

    provider._owns_session = True
    provider.get_price = lambda symbol: object()

    assert provider.connect() is True

    provider.disconnect()
    provider.disconnect()

    assert provider.connected is False
    assert session.close_count == 1


def test_connect_is_idempotent_while_connected() -> None:
    session = FakeSession()

    provider = BinancePublicDataProvider(
        session=session,
    )

    provider.get_price = lambda symbol: object()

    assert provider.connect() is True
    assert provider.connect() is True

    assert provider.connected is True
    assert session.close_count == 0
