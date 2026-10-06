"""App settings, read from environment variables only.

Every value is checked at startup. If something is missing or wrong the app
refuses to start (fail closed) instead of running with a weak default.
"""

import os

VALID_ENVS = {"dev", "prod"}
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
MIN_SECRET_KEY_LENGTH = 32


class ConfigError(Exception):
    """Raised when an environment variable is missing or invalid."""


def load_config(environ=None):
    """Build the Flask config dict from environment variables."""
    env = os.environ if environ is None else environ

    database_url = env.get("DATABASE_URL", "").strip()
    if not database_url:
        raise ConfigError("DATABASE_URL is required")

    secret_key = env.get("SECRET_KEY", "")
    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        # Short keys make session cookies easy to forge. Generate one with:
        # python -c "import secrets; print(secrets.token_urlsafe(48))"
        raise ConfigError(
            f"SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters"
        )

    app_env = env.get("APP_ENV", "dev")
    if app_env not in VALID_ENVS:
        raise ConfigError(f"APP_ENV must be one of {sorted(VALID_ENVS)}")

    log_level = env.get("LOG_LEVEL", "INFO").upper()
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {sorted(VALID_LOG_LEVELS)}")

    try:
        threshold = int(env.get("LOW_STOCK_THRESHOLD", "10"))
    except ValueError:
        raise ConfigError("LOW_STOCK_THRESHOLD must be a whole number") from None
    if threshold < 0:
        raise ConfigError("LOW_STOCK_THRESHOLD must not be negative")

    return {
        "SQLALCHEMY_DATABASE_URI": database_url,
        # Check the connection before using it, so a Postgres restart does not
        # leave the app holding dead connections.
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
        "SECRET_KEY": secret_key,
        "APP_ENV": app_env,
        "LOG_LEVEL": log_level,
        "LOW_STOCK_THRESHOLD": threshold,
        # Reject request bodies over 64 KB; nothing in this app needs more.
        "MAX_CONTENT_LENGTH": 64 * 1024,
        # Session cookie: not readable from JavaScript, not sent on
        # cross-site POSTs, and only sent over HTTPS in prod.
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": app_env == "prod",
        "REMEMBER_COOKIE_HTTPONLY": True,
        "REMEMBER_COOKIE_SECURE": app_env == "prod",
    }
