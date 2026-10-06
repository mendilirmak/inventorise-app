"""Smoke test against a DEPLOYED app (used by the Jenkins pipeline).

    BASE_URL=http://inventory.local SMOKE_USER=smoke SMOKE_PASSWORD=... \\
        pytest tests/smoke

Skipped automatically when BASE_URL is not set (e.g. in unit-test runs).
Uses only the standard library, so it needs nothing beyond pytest.
"""

import json
import os
import urllib.error
import urllib.request
import uuid

import pytest

BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE_URL, reason="BASE_URL not set")


def call(method, path, body=None, token=None):
    """Send a request; return (status, parsed JSON or None)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None


def test_live_flow():
    user = os.environ["SMOKE_USER"]
    password = os.environ["SMOKE_PASSWORD"]

    status, body = call("POST", "/api/auth/login", {"username": user, "password": password})
    assert status == 200, f"login failed: {status}"
    token = body["token"]

    # Unique SKU so repeated or parallel runs never collide.
    sku = f"SMOKE-{uuid.uuid4().hex[:8]}"
    status, product = call(
        "POST",
        "/api/products",
        {"name": "Smoke test item", "sku": sku, "price": 1.0, "stock_level": 1},
        token,
    )
    assert status == 201, product
    product_id = product["id"]

    try:
        status, restock = call(
            "POST", f"/api/products/{product_id}/restock", {"quantity": 2}, token
        )
        assert status == 201, restock
        assert restock["stock_level"] == 3

        status, low = call("GET", "/api/products/low-stock", token=token)
        assert status == 200
        assert sku in [p["sku"] for p in low], "3 units should be below the threshold"
    finally:
        # Always clean up, even when an assert above failed.
        status, _ = call("DELETE", f"/api/products/{product_id}", token=token)
    assert status == 204

    status, _ = call("GET", f"/api/products/{product_id}", token=token)
    assert status == 404

    status, _ = call("GET", "/api/products")
    assert status == 401, "API must refuse requests without a token"
