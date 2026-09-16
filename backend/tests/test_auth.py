from httpx import AsyncClient


async def test_create_user_success(client: AsyncClient):
    """
    Test successful user registration.
    """
    response = await client.post(
        "/register",
        json={"name": "Test User", "email": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    # ... other assertions


async def test_create_user_duplicate_email(client: AsyncClient):
    """
    Test registration with an email that already exists.
    """
    # First, create the user
    await client.post(
        "/register",
        json={"name": "Test User", "email": "test@example.com", "password": "password123"},
    )
    # Then, try to create it again
    response = await client.post(
        "/register",
        json={"name": "Another User", "email": "test@example.com", "password": "password456"},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


async def test_login_for_access_token_success(client: AsyncClient):
    """
    Test successful login and token generation.
    """
    # First, create a user to log in with
    await client.post(
        "/register",
        json={"name": "Login User", "email": "login@example.com", "password": "password123"},
    )

    # Now, log in
    response = await client.post(
        "/login/access-token",
        data={"username": "login@example.com", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_for_access_token_failure(client: AsyncClient):
    """
    Test login with incorrect password.
    """
    # Create a user
    await client.post(
        "/register",
        json={"name": "Login User", "email": "loginfail@example.com", "password": "password123"},
    )

    # Try to log in with the wrong password
    response = await client.post(
        "/login/access-token",
        data={"username": "loginfail@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]
