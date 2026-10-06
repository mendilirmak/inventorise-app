"""App factory: builds the Flask app and wires everything together.

Run with gunicorn: `gunicorn "app:create_app()"` (see Dockerfile).
"""

import json
import logging
import math
import sys
import time
from datetime import UTC, datetime

from flask import Flask, g, jsonify, render_template, request
from flask_wtf.csrf import CSRFProtect
from prometheus_client import CollectorRegistry, Gauge
from prometheus_flask_exporter import PrometheusMetrics
from sqlalchemy import func, select, text
from werkzeug.exceptions import HTTPException

from . import api, auth, cli, services, ui
from .config import load_config
from .models import Product, db

log = logging.getLogger(__name__)
csrf = CSRFProtect()

# Any number works; it just has to be the same in every app pod.
_CREATE_ALL_LOCK_ID = 7401

# Content-Security-Policy: the browser only runs scripts from this site and
# the pinned Chart.js CDN URL, and the page cannot be framed (clickjacking).
# With DevTools open, the browser console shows the Chart.js source map
# (chart.umd.min.js.map) being blocked. That is expected and harmless: only
# DevTools asks for it, and allowing it would loosen the policy for no gain.
_CSP = (
    "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self'; img-src 'self' data:; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


class JsonFormatter(logging.Formatter):
    """One JSON object per log line, so log tools can parse it."""

    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def _setup_logging(level):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


def _create_tables(app):
    """db.create_all(), safe when several pods start at the same time.

    On Postgres an advisory lock (a named lock held by the database) makes
    the pods take turns, so two of them never create the same table at once.
    """
    with app.app_context():
        if db.engine.dialect.name == "postgresql":
            with db.engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _CREATE_ALL_LOCK_ID})
                db.metadata.create_all(conn)
        else:
            db.create_all()


def _setup_metrics(app):
    # A registry per app instance, so tests can build many apps without
    # "metric already registered" errors.
    registry = CollectorRegistry()
    # group_by="endpoint" labels requests by route name, not by raw path, so
    # /api/products/1, /2, /3 ... do not each create a new time series.
    PrometheusMetrics(app, registry=registry, group_by="endpoint")

    gauge = Gauge(
        "inventory_low_stock_products",
        "Number of products with stock below LOW_STOCK_THRESHOLD",
        registry=registry,
    )

    def count_low_stock():
        # Runs inside the /metrics request. If the database is down, report
        # NaN (and log it) rather than failing the whole scrape.
        try:
            threshold = app.config["LOW_STOCK_THRESHOLD"]
            query = select(func.count()).where(Product.stock_level < threshold)
            return db.session.scalar(query)
        except Exception:
            log.exception("could not count low-stock products for metrics")
            db.session.rollback()
            return math.nan

    gauge.set_function(count_low_stock)


def _register_health_routes(app):
    @app.get("/health/live")
    def live():
        return jsonify(status="ok")

    @app.get("/health/ready")
    def ready():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            log.exception("readiness check failed: database not reachable")
            db.session.rollback()
            return jsonify(status="unavailable"), 503
        return jsonify(status="ok")


def _register_request_logging(app):
    @app.before_request
    def start_timer():
        g.start_time = time.perf_counter()

    @app.after_request
    def log_request(response):
        started = g.get("start_time", time.perf_counter())
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        # Probes and Prometheus hit these every few seconds; keep them out
        # of the normal log unless LOG_LEVEL=DEBUG.
        noisy = request.path.startswith("/health/") or request.path == "/metrics"
        log.log(
            logging.DEBUG if noisy else logging.INFO,
            "request",
            extra={
                "fields": {
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                }
            },
        )
        return response

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response


def _register_error_handlers(app):
    def wants_json():
        return request.path.startswith("/api/")

    @app.errorhandler(HTTPException)
    def http_error(exc):
        if wants_json():
            return jsonify(error=exc.description), exc.code
        return render_template("error.html", code=exc.code, message=exc.description), exc.code

    @app.errorhandler(services.ServiceError)
    def service_error(exc):
        # Reached only from UI routes that do not catch the error themselves.
        return render_template("error.html", code=exc.status, message=str(exc)), exc.status

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        # Full details go to the server log, never to the client.
        log.exception("unhandled error on %s %s", request.method, request.path)
        db.session.rollback()
        if wants_json():
            return jsonify(error="internal server error"), 500
        return render_template("error.html", code=500, message="Something went wrong."), 500


def create_app(environ=None, overrides=None):
    """Build the app.

    Config comes from the real environment variables. Tests pass their own
    `environ` dict instead, and `overrides` for extra Flask settings.
    """
    app = Flask(__name__)
    app.config.update(load_config(environ))
    app.config.update(overrides or {})

    _setup_logging(app.config["LOG_LEVEL"])
    db.init_app(app)
    auth.login_manager.init_app(app)
    csrf.init_app(app)

    app.register_blueprint(auth.bp)
    app.register_blueprint(ui.bp)
    app.register_blueprint(api.bp)
    # The API uses bearer tokens, not cookies, so it cannot be attacked
    # with cross-site requests and does not need CSRF tokens.
    csrf.exempt(api.bp)
    csrf.exempt(auth.api_login)

    _register_health_routes(app)
    _register_request_logging(app)
    _register_error_handlers(app)
    _setup_metrics(app)
    cli.register(app)

    _create_tables(app)
    log.info("app started", extra={"fields": {"app_env": app.config["APP_ENV"]}})
    return app
