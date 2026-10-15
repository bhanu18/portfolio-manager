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


# --- POST /trades/import -------------------------------------------------------------

YAHOO_EXPORT = (
    "Symbol,Current Price,Date,Trade Date,Purchase Price,Quantity,Commission,High Limit,"
    "Transaction Type\n"
    "NVDA,219.5,2026/09/18,20241122,142.1,2.0,0.0,,BUY\n"
    "NVDA,219.5,2026/09/18,20241206,145.53,1.0,0.51,,SELL\n"
    "AAPL,230.1,2026/09/18,20260302,201.25,3.0,0.0,,BUY\n"
)


@pytest.fixture
def no_asset_lookup(monkeypatch):
    """New assets would otherwise be looked up on Yahoo over the network."""
    from service.imports import pipeline

    monkeypatch.setattr(
        pipeline,
        "lookup_asset_details",
        lambda symbols: {s: {"name": s, "market": "NASDAQ", "type": "stock"} for s in symbols},
    )


@pytest.fixture
async def group_id(
    db_session: AsyncSession, trade_fixture: orm_models.Trade, member_headers: dict[str, str]
) -> int:
    """The member's group id, reloaded after member_headers expired the session."""
    await db_session.refresh(trade_fixture)
    return trade_fixture.group_id


async def _import(client, headers, group_id, *, dry_run, content=YAHOO_EXPORT, name="y.csv"):
    return await client.post(
        "/trades/import",
        headers=headers,
        data={"group_id": str(group_id), "dry_run": str(dry_run).lower()},
        files={"file": (name, content.encode() if isinstance(content, str) else content)},
    )


async def _trade_count(db_session: AsyncSession, group: int) -> int:
    db_session.expire_all()
    return len(await service.get_trades_by_group_id(db_session, group_id=group))


async def test_import_dry_run_reports_without_writing(
    client, db_session, group_id, member_headers, no_asset_lookup
):
    before = await _trade_count(db_session, group_id)
    response = await _import(client, member_headers, group_id, dry_run=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dry_run"] is True
    assert body["source"] == "yahoo"
    assert body["inserted"] == 3
    assert body["assets_created"] == ["NVDA"]  # AAPL already exists
    assert await _trade_count(db_session, group_id) == before


async def test_import_is_idempotent(client, db_session, group_id, member_headers, no_asset_lookup):
    before = await _trade_count(db_session, group_id)
    first = await _import(client, member_headers, group_id, dry_run=False)
    assert first.status_code == 200, first.text
    assert first.json()["inserted"] == 3
    assert await _trade_count(db_session, group_id) == before + 3

    again = await _import(client, member_headers, group_id, dry_run=False)
    assert again.json()["inserted"] == 0
    assert again.json()["unchanged"] == 3
    assert await _trade_count(db_session, group_id) == before + 3


async def test_import_requires_group_membership(client, group_id, no_asset_lookup):
    outsider = await _login(client, "outsider@example.com")
    response = await _import(client, outsider, group_id, dry_run=True)
    assert response.status_code == 403


async def test_import_rejects_other_file_types(client, group_id, member_headers):
    response = await _import(client, member_headers, group_id, dry_run=True, name="notes.txt")
    assert response.status_code == 422


async def test_import_rejects_oversized_file(client, group_id, member_headers):
    response = await _import(
        client, member_headers, group_id, dry_run=True, content=b"x" * (2**21 + 1)
    )
    assert response.status_code == 413


# ---- CRUD: list by group, create, update, delete ----


@pytest.fixture
async def outsider_headers(client: AsyncClient) -> dict[str, str]:
    """Auth headers for a logged-in user who is in no group."""
    return await _login(client, "outsider@example.com")


@pytest.fixture
async def ids(
    db_session: AsyncSession, trade_fixture: orm_models.Trade, member_headers: dict[str, str]
) -> dict[str, int]:
    """The fixture trade's ids, read after member_headers has expired every instance."""
    await db_session.refresh(trade_fixture)
    return {
        "trade": trade_fixture.id,
        "group": trade_fixture.group_id,
        "asset": trade_fixture.asset_id,
    }


NEW_TRADE = {
    "trade_type": "buy",
    "trade_date": "2026-02-01T09:00:00",
    "quantity": 5,
    "price_per_unit": 200.0,
    "currency": "USD",
}


async def test_read_trades_for_group_as_member(
    client: AsyncClient, ids: dict[str, int], member_headers: dict[str, str]
):
    response = await client.get(f"/trades/in-group/{ids['group']}", headers=member_headers)

    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [ids["trade"]]


async def test_read_trades_for_group_rejects_outsider(
    client: AsyncClient, ids: dict[str, int], outsider_headers: dict[str, str]
):
    response = await client.get(f"/trades/in-group/{ids['group']}", headers=outsider_headers)
    assert response.status_code == 403


async def test_read_trades_for_unknown_group(client: AsyncClient, member_headers: dict[str, str]):
    response = await client.get("/trades/in-group/999999", headers=member_headers)
    assert response.status_code == 404


async def test_read_trades_for_group_requires_login(client: AsyncClient, ids: dict[str, int]):
    response = await client.get(f"/trades/in-group/{ids['group']}")
    assert response.status_code == 401


async def test_create_trade_as_member(
    client: AsyncClient,
    db_session: AsyncSession,
    ids: dict[str, int],
    member_headers: dict[str, str],
):
    body = {**NEW_TRADE, "group_id": ids["group"]}
    response = await client.post("/trades/?symbol=aapl", json=body, headers=member_headers)

    assert response.status_code == 201
    created = response.json()
    assert created["asset_id"] == ids["asset"]
    assert created["quantity"] == 5
    assert await _trade_count(db_session, ids["group"]) == 2


async def test_create_trade_rejects_outsider(
    client: AsyncClient,
    db_session: AsyncSession,
    ids: dict[str, int],
    outsider_headers: dict[str, str],
):
    body = {**NEW_TRADE, "group_id": ids["group"]}
    response = await client.post("/trades/?symbol=AAPL", json=body, headers=outsider_headers)

    assert response.status_code == 403
    assert await _trade_count(db_session, ids["group"]) == 1


async def test_create_trade_unknown_group(client: AsyncClient, member_headers: dict[str, str]):
    body = {**NEW_TRADE, "group_id": 999999}
    response = await client.post("/trades/?symbol=AAPL", json=body, headers=member_headers)
    assert response.status_code == 404


async def test_create_trade_unknown_symbol(
    client: AsyncClient, ids: dict[str, int], member_headers: dict[str, str]
):
    body = {**NEW_TRADE, "group_id": ids["group"]}
    response = await client.post("/trades/?symbol=NOPE", json=body, headers=member_headers)
    assert response.status_code == 404


async def test_create_trade_validates_body(
    client: AsyncClient, ids: dict[str, int], member_headers: dict[str, str]
):
    body = {**NEW_TRADE, "group_id": ids["group"], "trade_type": "short"}
    response = await client.post("/trades/?symbol=AAPL", json=body, headers=member_headers)
    assert response.status_code == 422


async def test_update_trade_as_member(
    client: AsyncClient, ids: dict[str, int], member_headers: dict[str, str]
):
    response = await client.patch(
        f"/trades/{ids['trade']}", json={"quantity": 7}, headers=member_headers
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == 7
    # Fields not in the body are left alone.
    assert response.json()["price_per_unit"] == 190.5


async def test_update_trade_rejects_outsider(
    client: AsyncClient,
    db_session: AsyncSession,
    ids: dict[str, int],
    outsider_headers: dict[str, str],
):
    response = await client.patch(
        f"/trades/{ids['trade']}", json={"quantity": 7}, headers=outsider_headers
    )

    assert response.status_code == 403
    db_session.expire_all()
    trade = await service.get_trade_by_id(db_session, trade_id=ids["trade"])
    assert trade.quantity == 10


async def test_update_unknown_trade(client: AsyncClient, member_headers: dict[str, str]):
    response = await client.patch("/trades/999999", json={"quantity": 7}, headers=member_headers)
    assert response.status_code == 404


async def test_delete_trade_as_member(
    client: AsyncClient,
    db_session: AsyncSession,
    ids: dict[str, int],
    member_headers: dict[str, str],
):
    response = await client.delete(f"/trades/{ids['trade']}", headers=member_headers)

    assert response.status_code == 204
    assert await _trade_count(db_session, ids["group"]) == 0


async def test_delete_trade_rejects_outsider(
    client: AsyncClient,
    db_session: AsyncSession,
    ids: dict[str, int],
    outsider_headers: dict[str, str],
):
    response = await client.delete(f"/trades/{ids['trade']}", headers=outsider_headers)

    assert response.status_code == 403
    assert await _trade_count(db_session, ids["group"]) == 1


async def test_delete_unknown_trade(client: AsyncClient, member_headers: dict[str, str]):
    response = await client.delete("/trades/999999", headers=member_headers)
    assert response.status_code == 404
