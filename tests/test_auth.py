"""Login, logout, tokens, CSRF and the create-user command."""

from datetime import UTC, datetime, timedelta

import pytest

from app import create_app
from app.auth import UserError, set_user_password
from app.models import User, db
from tests.conftest import PASSWORD, TEST_ENV, USERNAME


def login(client, username=USERNAME, password=PASSWORD):
    return client.post("/login", data={"username": username, "password": password})


# --- browser session ---------------------------------------------------------


def test_pages_redirect_to_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_page_is_open(client):
    assert client.get("/login").status_code == 200


def test_browser_login_and_logout(client):
    assert login(client).status_code == 302
    assert client.get("/").status_code == 200
    client.post("/logout")
    assert client.get("/").status_code == 302


def test_wrong_password_and_unknown_user_look_the_same(client):
    wrong_password = login(client, password="wrong-password-123")
    unknown_user = login(client, username="nobody")
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert client.get("/").status_code == 302


def test_login_ignores_offsite_next(client):
    response = client.post(
        "/login?next=//evil.example/x",
        data={"username": USERNAME, "password": PASSWORD},
    )
    assert response.headers["Location"] == "/"


def test_session_cookie_flags(client):
    login(client)
    cookie = client.get_cookie("session")
    assert cookie.http_only
    assert cookie.same_site == "Lax"


def test_secure_cookie_in_prod():
    app = create_app({**TEST_ENV, "APP_ENV": "prod"})
    assert app.config["SESSION_COOKIE_SECURE"] is True


def test_csrf_blocks_form_post_without_token():
    app = create_app(TEST_ENV, {"TESTING": True})  # CSRF left on
    with app.app_context():
        set_user_password(USERNAME, PASSWORD)
        response = app.test_client().post(
            "/login", data={"username": USERNAME, "password": PASSWORD}
        )
        assert response.status_code == 400


# --- API token ---------------------------------------------------------------


def test_api_needs_token(client):
    response = client.get("/api/products")
    assert response.status_code == 401
    assert response.get_json() == {"error": "missing, invalid or expired token"}


def test_api_rejects_session_cookie(client):
    login(client)
    assert client.get("/api/products").status_code == 401


def test_api_login_returns_token(client):
    response = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"token", "expires_at"}
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert client.get("/api/products", headers=headers).status_code == 200


def test_api_login_wrong_password(client):
    response = client.post("/api/auth/login", json={"username": USERNAME, "password": "nope"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [None, [], {"username": USERNAME}, {"username": USERNAME, "password": PASSWORD, "x": 1}],
)
def test_api_login_bad_body(client, body):
    assert client.post("/api/auth/login", json=body).status_code == 400


def test_token_stored_only_as_hash(app, token):
    user = db.session.query(User).filter_by(username=USERNAME).one()
    assert user.api_token_hash != token
    assert len(user.api_token_hash) == 64  # SHA-256 hex


def test_expired_token_rejected(app, client, token):
    user = db.session.query(User).filter_by(username=USERNAME).one()
    user.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.session.commit()
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/products", headers=headers).status_code == 401


def test_new_login_replaces_old_token(client, token):
    client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/products", headers=headers).status_code == 401


def test_open_endpoints(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert b"inventory_low_stock_products" in metrics.data


# --- users ---------------------------------------------------------------------


def test_create_user_is_idempotent(app, client, token):
    assert set_user_password(USERNAME, "a-brand-new-password") is False
    # Old password and old token stop working.
    assert login(client).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/products", headers=headers).status_code == 401
    assert login(client, password="a-brand-new-password").status_code == 302


@pytest.mark.parametrize(
    "username, password",
    [("ab", PASSWORD), ("ok-user", "short"), ("bad user", PASSWORD)],
)
def test_create_user_validation(app, username, password):
    with pytest.raises(UserError):
        set_user_password(username, password)


def test_create_user_cli(app):
    runner = app.test_cli_runner()
    typed = "long-enough-pass\nlong-enough-pass\n"  # password + confirmation
    result = runner.invoke(args=["create-user", "clerk"], input=typed)
    assert result.exit_code == 0, result.output
    assert "created" in result.output
    result = runner.invoke(args=["create-user", "clerk", "--password", "another-long-pass"])
    assert "password updated" in result.output
