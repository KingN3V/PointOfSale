import pytest

from pos.limiter import limiter


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """The limiter counts requests in memory for the whole test run, so
    empty it before and after each test in this file."""
    limiter.reset()
    yield
    limiter.reset()


def login(client, username, password):
    return client.post(
        "/auth/token",
        data={"username": username, "password": password},
    )


def test_login_works_and_wrong_password_is_refused(client, auth_headers):
    # auth_headers creates the user "shopowner" with password "password123".
    r = login(client, "shopowner", "password123")
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    assert r.json()["access_token"]

    assert login(client, "shopowner", "wrong-password").status_code == 401


def test_login_is_rate_limited_after_10_attempts(client, auth_headers):
    statuses = [login(client, "shopowner", "wrong-password").status_code for _ in range(12)]

    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    assert statuses[11] == 429


def test_forgot_password_is_rate_limited_after_5_attempts(client):
    statuses = [
        client.post("/auth/forgot-password", json={"email": "nobody@example.com"}).status_code
        for _ in range(7)
    ]

    assert statuses[:5] == [200] * 5
    assert statuses[5] == 429
    assert statuses[6] == 429