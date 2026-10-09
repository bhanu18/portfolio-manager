"""Batch lookup is bounded, reads with one query, and works for regular users."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event

from db.orm_models import Asset


@pytest.fixture
async def asset_rows(db_session):
    now = datetime.now(UTC).replace(tzinfo=None)
    assets = [
        Asset(
            symbol=symbol,
            name=name,
            market="NASDAQ",
            type="stock",
            current_price=price,
            price_last_updated=now,
            created_at=now,
            updated_at=now,
        )
        for symbol, name, price in [("AAPL", "Apple", 100.0), ("MSFT", "Microsoft", 200.0)]
    ]
    db_session.add_all(assets)
    await db_session.commit()
    for asset in assets:
        await db_session.refresh(asset)
    return assets


@pytest.fixture
async def regular_headers(client):
    await client.post(
        "/register",
        json={
            "name": "batch-reader",
            "email": "batch-reader@example.com",
            "password": "password123",
        },
    )
    response = await client.post(
        "/login/access-token",
        data={"username": "batch-reader@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_batch_requires_auth(client, asset_rows):
    response = await client.post("/assets/batch", json={"ids": [asset_rows[0].id]})
    assert response.status_code == 401


async def test_batch_returns_stored_assets_once_in_request_order(
    client, db_session, regular_headers, asset_rows
):
    first, second = asset_rows
    statements = []
    connection = await db_session.connection()

    def track(conn, cursor, statement, parameters, context, executemany):
        if "from assets" in statement.lower():
            statements.append(statement)

    event.listen(connection.sync_connection, "before_cursor_execute", track)
    try:
        response = await client.post(
            "/assets/batch",
            headers=regular_headers,
            json={"ids": [second.id, first.id, second.id, second.id + 999999]},
        )
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", track)
    assert response.status_code == 200
    assert [asset["id"] for asset in response.json()] == [second.id, first.id]
    assert response.json()[0]["symbol"] == "MSFT"
    assert response.json()[0]["current_price"] == 200.0
    assert response.json()[0]["price_last_updated"] is not None
    assert len(statements) == 1
    assert " IN " in statements[0]


async def test_batch_all_missing_returns_empty_list(client, regular_headers):
    response = await client.post("/assets/batch", headers=regular_headers, json={"ids": [99999999]})
    assert response.status_code == 200 and response.json() == []


@pytest.mark.parametrize("ids", [[], [0], [-1], ["1"], [True], [1.5], list(range(1, 502))])
async def test_batch_rejects_invalid_or_oversized_requests(client, regular_headers, ids):
    response = await client.post("/assets/batch", headers=regular_headers, json={"ids": ids})
    assert response.status_code == 422


async def test_batch_accepts_maximum_size(client, regular_headers, asset_rows):
    asset_id = asset_rows[0].id
    response = await client.post(
        "/assets/batch", headers=regular_headers, json={"ids": [asset_id] * 500}
    )
    assert response.status_code == 200
    assert [asset["id"] for asset in response.json()] == [asset_id]
