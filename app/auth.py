"""Login for people (browser session) and for scripts (API bearer token).

- Browser: GET/POST /login, POST /logout. Flask-Login keeps the user id in a
  signed session cookie.
- API: POST /api/auth/login returns a random token valid for 24 hours.
  Only its SHA-256 hash is stored, so a leaked database gives no usable
  tokens. Every other /api/* request must send `Authorization: Bearer <token>`.

Users are created only from the command line (cli.py). There is no
registration page, no lockout and no rate limiting (see SECURITY.md).
"""

import hashlib
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta

from flask import (
    Blueprint,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from .models import User, as_utc, db

log = logging.getLogger(__name__)

TOKEN_LIFETIME = timedelta(hours=24)
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256
# Checked when the username does not exist, so a wrong username takes as
# long as a wrong password and an attacker cannot tell which one was wrong.
_DUMMY_HASH = generate_password_hash("not-a-real-password")

login_manager = LoginManager()
login_manager.login_view = "auth.login_page"
login_manager.session_protection = "strong"

bp = Blueprint("auth", __name__)


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except ValueError:
        return None


# --- user management (used by cli.py) ----------------------------------------


class UserError(Exception):
    pass


def set_user_password(username, password):
    """Create the user, or update the password if the user exists.

    Returns True if a new user was created. Changing the password also
    revokes the user's API token.
    """
    if not USERNAME_PATTERN.match(username):
        raise UserError("username must be 3-64 characters: letters, digits, '_', '.', '-'")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise UserError(
            f"password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters"
        )

    user = db.session.scalar(select(User).where(User.username == username))
    created = user is None
    if created:
        user = User(username=username)
        db.session.add(user)
    user.password_hash = generate_password_hash(password)  # scrypt by default
    user.api_token_hash = None
    user.token_expires_at = None
    db.session.commit()
    log.info(
        "user %s",
        "created" if created else "password changed",
        extra={"fields": {"event": "user_created" if created else "password_changed",
                          "username": username}},
    )
    return created


# --- shared helpers ------------------------------------------------------------


def _check_credentials(username, password):
    """Return the User if the username and password match, else None."""
    if not isinstance(username, str) or not isinstance(password, str):
        return None
    if len(username) > 64 or len(password) > MAX_PASSWORD_LENGTH:
        return None
    user = db.session.scalar(select(User).where(User.username == username))
    if user is None:
        check_password_hash(_DUMMY_HASH, password)
        return None
    if not check_password_hash(user.password_hash, password):
        return None
    return user


def _log_login(kind, username, success):
    # Truncate: the username is user input and may be very long.
    username = username[:64] if isinstance(username, str) else "<invalid>"
    log.log(
        logging.INFO if success else logging.WARNING,
        "login %s",
        "success" if success else "failure",
        extra={
            "fields": {
                "event": "login",
                "kind": kind,
                "username": username,
                "ip": request.remote_addr,
                "result": "success" if success else "failure",
            }
        },
    )


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _safe_next(target):
    """Only allow redirects to paths on this site (no open redirect)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("ui.dashboard")


# --- browser login -------------------------------------------------------------


@bp.get("/login")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("ui.dashboard"))
    return render_template("login.html")


@bp.post("/login")
def login_submit():
    username = request.form.get("username", "")
    user = _check_credentials(username, request.form.get("password", ""))
    _log_login("session", username, user is not None)
    if user is None:
        flash("Wrong username or password.", "error")
        return render_template("login.html", username=username[:64]), 401
    login_user(user)
    return redirect(_safe_next(request.args.get("next")))


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login_page"))


# --- API login and token check -------------------------------------------------


@bp.post("/api/auth/login")
def api_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {"username", "password"}:
        return jsonify(error="body must be JSON with exactly: username, password"), 400

    user = _check_credentials(data["username"], data["password"])
    _log_login("api", data["username"], user is not None)
    if user is None:
        return jsonify(error="wrong username or password"), 401

    # One active token per user: a new login replaces the old token.
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + TOKEN_LIFETIME
    user.api_token_hash = _hash_token(token)
    user.token_expires_at = expires_at
    db.session.commit()
    return jsonify(token=token, expires_at=expires_at.isoformat())


def require_api_token():
    """before_request hook for the API blueprint. Returns a 401 or None.

    The session cookie is deliberately NOT accepted here: bearer-only means
    the API cannot be abused through cross-site requests (CSRF).
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 128:
        return _unauthorized()

    # Look up by hash. The token is 32 random bytes, so guessing a hash
    # through timing differences is not practical.
    user = db.session.scalar(select(User).where(User.api_token_hash == _hash_token(token)))
    if user is None or as_utc(user.token_expires_at) <= datetime.now(UTC):
        return _unauthorized()
    g.api_user = user
    return None


def _unauthorized():
    log.warning(
        "api access denied",
        extra={
            "fields": {
                "event": "api_auth_denied",
                "path": request.path,
                "ip": request.remote_addr,
            }
        },
    )
    response = jsonify(error="missing, invalid or expired token")
    response.status_code = 401
    response.headers["WWW-Authenticate"] = "Bearer"
    return response
