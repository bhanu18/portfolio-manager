from fastapi.testclient import TestClient

def test_create_user_success(client: TestClient):
    """
    Test successful user registration.
    """
    response = client.post(
        "/register",
        json={"name": "Test User", "email": "test@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["name"] == "Test User"
    assert "id" in data
    assert "hashed_password" not in data # Ensure password is not returned

def test_create_user_duplicate_email(client: TestClient):
    """
    Test registration with an email that already exists.
    """
    # First, create the user
    client.post(
        "/register",
        json={"name": "Test User", "email": "test@example.com", "password": "password123"},
    )
    # Then, try to create it again
    response = client.post(
        "/register",
        json={"name": "Another User", "email": "test@example.com", "password": "password456"},
    )
    assert response.status_code == 400
    assert "email already exists" in response.json()["detail"].lower()

def test_login_for_access_token_success(client: TestClient):
    """
    Test successful login and token generation.
    """
    # First, create a user to log in with
    client.post(
        "/register",
        json={"name": "Login User", "email": "login@example.com", "password": "password123"},
    )
    
    # Now, log in
    response = client.post(
        "/login/access-token",
        data={"username": "login@example.com", "password": "password123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_login_for_access_token_failure(client: TestClient):
    """
    Test login with incorrect password.
    """
    # Create a user
    client.post(
        "/register",
        json={"name": "Login User", "email": "loginfail@example.com", "password": "password123"},
    )
    
    # Try to log in with the wrong password
    response = client.post(
        "/login/access-token",
        data={"username": "loginfail@example.com", "password": "wrongpassword"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]