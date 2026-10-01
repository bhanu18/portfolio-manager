"""Trades API: the shape of what GET /trades/symbol/{symbol} returns.

Covers the row-bookkeeping timestamps (created_at / updated_at) and the
integer `id` — TradeResponse declared `id: str`, which pydantic v2 will not
coerce from an int, so every request to this endpoint used to 500. Also checks
the endpoint requires login and only returns trades from the caller's groups.
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from db import orm_models, service
from models.trade import TradeUpdate

# Naive on purpose: trades.trade_date is a naive DateTime column, same as the rest
# of the schema (see the DTZ003 ignore in pyproject.toml).
TRADE_DATE = datetime(2026, 1, 15, 10, 30)  # noqa: DTZ001


@pytest.fixture
async def trade_fixture(db_session: AsyncSession) -> orm_models.Trade:
    """An asset in a group with a single buy trade against it."""
    asset = orm_models.Asset(
        symbol="AAPL",
        name="Apple Inc.",
        market="NASDAQ",
        type="stock",
        created_at=TRADE_DATE,
        updated_at=TRADE_DATE,
    )
    group = orm_models.Group(name="Test Group")
    db_session.add_all([asset, group])
    await db_session.flush()

    trade = orm_models.Trade(
        asset_id=asset.id,
        group_id=group.id,
        trade_type="buy",
        trade_date=TRADE_DATE,
        quantity=10,
        price_per_unit=190.5,
        currency="USD",
    )
    db_session.add(trade)
    await db_session.commit()
    await db_session.refresh(trade)
    return trade


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    await client.post(
        "/register", json={"name": email.split("@")[0], "email": email, "password": "password123"}
    )
    response = await client.post(
        "/login/access-token", data={"username": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def member_headers(
    client: AsyncClient, db_session: AsyncSession, trade_fixture: orm_models.Trade
) -> dict[str, str]:
    """Auth headers for a user who belongs to the trade's group."""
    headers = await _login(client, "member@example.com")
    user = await service.get_user_by_email(db_session, email="member@example.com")
    db_session.add(
        orm_models.UserGroupAssociation(
            user_id=user.id,
            group_id=trade_fixture.group_id,
            role=orm_models.GroupMemberRole.MEMBER,
        )
    )
    await db_session.commit()
    db_session.expire_all()
    return headers


async def test_trade_row_gets_timestamps_on_insert(trade_fixture: orm_models.Trade):
    """The database fills both columns without the caller supplying them."""
    assert trade_fixture.created_at is not None
    assert trade_fixture.updated_at is not None
    # Fresh row: the two are written by the same statement.
    assert abs(trade_fixture.updated_at - trade_fixture.created_at) < timedelta(seconds=2)
    # The bookkeeping clock is "now", not the trade's own date.
    assert trade_fixture.created_at > TRADE_DATE


async def test_update_bumps_updated_at_only(
    db_session: AsyncSession, trade_fixture: orm_models.Trade
):
    """onupdate moves updated_at; created_at stays put."""
    created_at = trade_fixture.created_at
    original_updated_at = trade_fixture.updated_at

    await service.update_trade(
        db_session, db_trade=trade_fixture, trade_in=TradeUpdate(quantity=12)
    )
    await db_session.refresh(trade_fixture)

    assert trade_fixture.quantity == 12
    assert trade_fixture.created_at == created_at
    assert trade_fixture.updated_at >= original_updated_at


async def test_read_trades_by_symbol_returns_timestamps(
    client: AsyncClient, trade_fixture: orm_models.Trade, member_headers: dict[str, str]
):
    """The endpoint serialises, and the timestamps reach the client."""
    response = await client.get("/trades/symbol/AAPL", headers=member_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]

    assert row["id"] == trade_fixture.id
    assert isinstance(row["id"], int)
    assert row["symbol"] == "AAPL"
    assert row["currency"] == "USD"
    # trade_date is the trade; created_at/updated_at are the record.
    assert row["trade_date"].startswith("2026-01-15")
    assert datetime.fromisoformat(row["created_at"]) == trade_fixture.created_at
    assert datetime.fromisoformat(row["updated_at"]) == trade_fixture.updated_at


async def test_read_trades_by_symbol_is_case_insensitive(
    client: AsyncClient, trade_fixture: orm_models.Trade, member_headers: dict[str, str]
):
    response = await client.get("/trades/symbol/aapl", headers=member_headers)
    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "AAPL"


async def test_read_trades_by_symbol_requires_login(
    client: AsyncClient, trade_fixture: orm_models.Trade
):
    response = await client.get("/trades/symbol/AAPL")
    assert response.status_code == 401


async def test_read_trades_by_symbol_hides_other_groups(
    client: AsyncClient, trade_fixture: orm_models.Trade
):
    """A logged-in user outside the trade's group sees nothing."""
    headers = await _login(client, "outsider@example.com")
    response = await client.get("/trades/symbol/AAPL", headers=headers)
    assert response.status_code == 404
