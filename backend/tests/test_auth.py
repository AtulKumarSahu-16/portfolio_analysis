import pytest


@pytest.mark.asyncio
async def test_signup_creates_user_session_and_logout_clears_it(api):
    client, _ = api
    created = await client.post("/api/auth/signup", json={"display_name": "Ada", "email": "ADA@example.com", "password": "correct-horse-battery-staple"})
    assert created.status_code == 201, created.json()
    assert created.json()["email"] == "ada@example.com"
    cookie = created.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api" in cookie
    assert "password_hash" not in created.json()

    current = await client.get("/api/auth/me")
    assert current.status_code == 200
    assert current.json()["display_name"] == "Ada"

    duplicate = await client.post("/api/auth/signup", json={"display_name": "Another", "email": "ada@example.com", "password": "another-long-password"})
    assert duplicate.status_code == 409

    logged_out = await client.post("/api/auth/logout", json={})
    assert logged_out.status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_login_rejects_wrong_password_and_accepts_correct_password(api):
    client, _ = api
    await client.post("/api/auth/signup", json={"display_name": "Lin", "email": "lin@example.com", "password": "a-secure-password-123"})
    await client.post("/api/auth/logout", json={})

    wrong = await client.post("/api/auth/login", json={"email": "lin@example.com", "password": "incorrect-password"})
    assert wrong.status_code == 401
    right = await client.post("/api/auth/login", json={"email": "LIN@example.com", "password": "a-secure-password-123"})
    assert right.status_code == 200
    assert right.json()["email"] == "lin@example.com"


@pytest.mark.asyncio
async def test_signup_validation_and_me_require_authentication(api):
    client, _ = api
    invalid = await client.post("/api/auth/signup", json={"display_name": "User", "email": "not-an-email", "password": "short"})
    assert invalid.status_code == 422
    current = await client.get("/api/auth/me")
    assert current.status_code == 401
