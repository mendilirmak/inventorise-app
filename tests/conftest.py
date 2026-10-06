"""Shared test setup: a fresh app with an in-memory SQLite database per test,
so the tests need no Postgres.

The app is imported inside the fixture, not at the top: pytest also loads
this file for tests/smoke, which runs against a deployed URL with only
pytest installed (no Flask).
"""

import pytest

TEST_ENV = {
    "DATABASE_URL": "sqlite://",  # in-memory database
    # Obviously fake, just long enough to pass the length check (and it
    # does not look like a real secret to the gitleaks scan).
    "SECRET_KEY": "x" * 40,
    "APP_ENV": "dev",
    "LOG_LEVEL": "WARNING",
    "LOW_STOCK_THRESHOLD": "10",
}
USERNAME = "tester"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def app():
    from app import create_app
    from app.auth import set_user_password
    from app.models import db

    # CSRF is switched off for most tests; test_auth.py checks it separately.
    app = create_app(TEST_ENV, {"TESTING": True, "WTF_CSRF_ENABLED": False})
    with app.app_context():
        set_user_password(USERNAME, PASSWORD)
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def token(client):
    response = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    return response.get_json()["token"]


@pytest.fixture
def api(client, token):
    """A test client that sends the bearer token on every request."""

    class Api:
        def __getattr__(self, method):
            def call(path, **kwargs):
                headers = {"Authorization": f"Bearer {token}", **kwargs.pop("headers", {})}
                return getattr(client, method)(path, headers=headers, **kwargs)

            return call

    return Api()


def product_payload(**changes):
    data = {
        "name": "Blue Mug",
        "sku": "MUG-BLUE",
        "description": "350 ml",
        "price": 7.5,
        "stock_level": 20,
    }
    data.update(changes)
    return data
