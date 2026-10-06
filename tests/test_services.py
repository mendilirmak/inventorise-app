"""Business rules in services.py, tested without HTTP."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app import services
from tests.conftest import product_payload


def test_create_and_get(app):
    product = services.create_product(product_payload())
    assert services.get_product(product.id).sku == "MUG-BLUE"
    assert product.price == Decimal("7.50")


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"stock_level": -1}, "stock_level"),
        ({"stock_level": "5"}, "stock_level"),
        ({"stock_level": True}, "stock_level"),
        ({"price": -0.01}, "price"),
        ({"price": "free"}, "price"),
        ({"name": "  "}, "name is required"),
        ({"sku": "has space"}, "sku"),
        ({"colour": "blue"}, "unknown field"),
    ],
)
def test_create_rejects_bad_input(app, changes, message):
    with pytest.raises(services.ValidationError, match=message):
        services.create_product(product_payload(**changes))


def test_create_rejects_missing_fields(app):
    with pytest.raises(services.ValidationError, match="missing field"):
        services.create_product({"name": "x"})


def test_duplicate_sku_is_conflict(app):
    services.create_product(product_payload())
    with pytest.raises(services.ConflictError):
        services.create_product(product_payload(name="Other"))


def test_update_to_existing_sku_is_conflict(app):
    services.create_product(product_payload())
    other = services.create_product(product_payload(sku="MUG-RED"))
    with pytest.raises(services.ConflictError):
        services.update_product(other.id, {"sku": "MUG-BLUE"})


def test_update_partial(app):
    product = services.create_product(product_payload())
    services.update_product(product.id, {"stock_level": 3})
    assert services.get_product(product.id).stock_level == 3
    assert services.get_product(product.id).name == "Blue Mug"


def test_restock_adds_stock_and_logs(app):
    product = services.create_product(product_payload(stock_level=2))
    services.restock_product(product.id, {"quantity": 5, "note": "delivery"})
    assert services.get_product(product.id).stock_level == 7
    [log] = services.list_restocks()
    assert (log.quantity, log.note) == (5, "delivery")


@pytest.mark.parametrize("quantity", [0, -3, "5", 1.5])
def test_restock_rejects_non_positive_or_non_integer(app, quantity):
    product = services.create_product(product_payload())
    with pytest.raises(services.ValidationError):
        services.restock_product(product.id, {"quantity": quantity})


def test_not_found(app):
    with pytest.raises(services.NotFoundError):
        services.get_product(999)
    with pytest.raises(services.NotFoundError):
        services.restock_product(999, {"quantity": 1})


def test_low_stock_is_strictly_below_threshold(app):
    services.create_product(product_payload(sku="A", stock_level=9))
    services.create_product(product_payload(sku="B", stock_level=10))
    assert [p.sku for p in services.low_stock_products(10)] == ["A"]


def test_delete_removes_restock_logs(app):
    product = services.create_product(product_payload())
    services.restock_product(product.id, {"quantity": 1})
    services.delete_product(product.id)
    assert services.list_restocks() == []


def test_analytics(app):
    a = services.create_product(product_payload(sku="A", stock_level=5))
    services.create_product(product_payload(sku="B", stock_level=50))
    services.restock_product(a.id, {"quantity": 1})
    services.restock_product(a.id, {"quantity": 1})

    data = services.analytics(10)
    assert data["total_stock"] == 57
    assert data["low_stock_count"] == 1
    assert len(data["restocks_per_day"]) == services.ANALYTICS_DAYS
    today = data["restocks_per_day"][-1]
    assert today == {"date": datetime.now(UTC).date().isoformat(), "count": 2}
