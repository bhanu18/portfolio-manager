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
    assert response.json()["detail"] == "Registration failed. Check your details or try logging in."


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


async def test_reset_token_is_single_use(client: AsyncClient, db_session):
    """Once a reset token has changed the password, it can't be replayed."""
    from db import service
    from service.security import create_password_reset_token

    await client.post(
        "/register",
        json={"name": "Reset User", "email": "reset@example.com", "password": "password123"},
    )
    user = await service.get_user_by_email(db_session, email="reset@example.com")
    token = create_password_reset_token(email=user.email, hashed_password=user.hashed_password)

    first = await client.post(
        "/reset-password", json={"token": token, "new_password": "newpassword123"}
    )
    assert first.status_code == 200

    replay = await client.post(
        "/reset-password", json={"token": token, "new_password": "attacker123"}
    )
    assert replay.status_code == 400

    login = await client.post(
        "/login/access-token",
        data={"username": "reset@example.com", "password": "newpassword123"},
    )
    assert login.status_code == 200


async def test_register_duplicate_name_is_generic_400(client: AsyncClient):
    """users.name is unique; a clash is a clean 400 with the same message, not a 500."""
    await client.post(
        "/register",
        json={"name": "Same Name", "email": "first@example.com", "password": "password123"},
    )
    response = await client.post(
        "/register",
        json={"name": "Same Name", "email": "second@example.com", "password": "password123"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Registration failed. Check your details or try logging in."


async def test_change_password_revokes_old_tokens(client: AsyncClient):
    """Tokens issued before a password change stop working; the returned one works."""
    await client.post(
        "/register",
        json={"name": "Rotate User", "email": "rotate@example.com", "password": "password123"},
    )
    login = await client.post(
        "/login/access-token",
        data={"username": "rotate@example.com", "password": "password123"},
    )
    old_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    change = await client.post(
        "/change-password",
        json={"current_password": "password123", "new_password": "newpassword123"},
        headers=old_headers,
    )
    assert change.status_code == 200
    new_headers = {"Authorization": f"Bearer {change.json()['access_token']}"}

    assert (await client.get("/users/me", headers=old_headers)).status_code == 401
    assert (await client.get("/users/me", headers=new_headers)).status_code == 200
