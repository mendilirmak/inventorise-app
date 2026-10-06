"""The JSON API: status codes and response shapes."""

from tests.conftest import product_payload


def test_crud_flow(api):
    created = api.post("/api/products", json=product_payload())
    assert created.status_code == 201
    product_id = created.get_json()["id"]

    assert api.get(f"/api/products/{product_id}").get_json()["sku"] == "MUG-BLUE"
    assert len(api.get("/api/products").get_json()) == 1

    updated = api.put(f"/api/products/{product_id}", json={"price": 9.99})
    assert updated.status_code == 200
    assert updated.get_json()["price"] == 9.99

    assert api.delete(f"/api/products/{product_id}").status_code == 204
    assert api.get(f"/api/products/{product_id}").status_code == 404


def test_validation_errors_are_400(api):
    response = api.post("/api/products", json=product_payload(stock_level=-5))
    assert response.status_code == 400
    assert "stock_level" in response.get_json()["error"]


def test_non_json_body_is_400(api):
    response = api.post("/api/products", data="not json", content_type="text/plain")
    assert response.status_code == 400


def test_duplicate_sku_is_409(api):
    api.post("/api/products", json=product_payload())
    assert api.post("/api/products", json=product_payload()).status_code == 409


def test_unknown_product_is_404(api):
    assert api.get("/api/products/12345").status_code == 404
    assert api.post("/api/products/12345/restock", json={"quantity": 1}).status_code == 404


def test_unknown_route_is_json_404(api):
    response = api.get("/api/nope")
    assert response.status_code == 404
    assert "error" in response.get_json()


def test_restock(api):
    product_id = api.post("/api/products", json=product_payload(stock_level=1)).get_json()["id"]
    response = api.post(f"/api/products/{product_id}/restock", json={"quantity": 4, "note": "x"})
    assert response.status_code == 201
    assert response.get_json()["stock_level"] == 5
    bad = api.post(f"/api/products/{product_id}/restock", json={"quantity": 0})
    assert bad.status_code == 400


def test_restocks_newest_first(api):
    product_id = api.post("/api/products", json=product_payload()).get_json()["id"]
    for quantity in (1, 2, 3):
        api.post(f"/api/products/{product_id}/restock", json={"quantity": quantity})
    history = api.get("/api/restocks").get_json()
    assert [r["quantity"] for r in history] == [3, 2, 1]
    assert history[0]["product_name"] == "Blue Mug"


def test_low_stock_and_analytics_routes_not_shadowed(api):
    # These paths must not be treated as /api/products/<id>.
    api.post("/api/products", json=product_payload(sku="LOW", stock_level=2))
    api.post("/api/products", json=product_payload(sku="HIGH", stock_level=200))

    low = api.get("/api/products/low-stock")
    assert low.status_code == 200
    assert [p["sku"] for p in low.get_json()] == ["LOW"]

    analytics = api.get("/api/products/analytics").get_json()
    assert analytics["low_stock_count"] == 1
    assert analytics["total_stock"] == 202


def test_errors_do_not_leak_internals(app, api, monkeypatch):
    from app import services

    def boom():
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(services, "list_products", boom)
    response = api.get("/api/products")
    assert response.status_code == 500
    assert response.get_json() == {"error": "internal server error"}
    assert b"secret" not in response.data


def test_security_headers(client):
    response = client.get("/login")
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_ui_create_product_and_restock(client):
    from tests.conftest import PASSWORD, USERNAME

    client.post("/login", data={"username": USERNAME, "password": PASSWORD})
    response = client.post("/products/new", data={**product_payload(), "price": "7.50"})
    assert response.status_code == 302
    product_url = response.headers["Location"]
    client.post(f"{product_url}/restock", data={"quantity": "3", "note": ""})
    page = client.get(product_url)
    assert b"23 units in stock" in page.data
    assert client.get("/").status_code == 200
