"""Business rules, used by both the JSON API (api.py) and the HTML UI (ui.py).
Each rule lives in one place.

On bad input the functions raise a ServiceError subclass. The caller turns it
into a JSON error or a flash message.
"""

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import Product, RestockLog, as_utc, db

PRODUCT_FIELDS = {"name", "sku", "description", "price", "stock_level"}
REQUIRED_PRODUCT_FIELDS = {"name", "sku", "price", "stock_level"}
RESTOCK_FIELDS = {"quantity", "note"}
SKU_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_STOCK = 1_000_000_000
MAX_PRICE = Decimal("99999999.99")  # largest value Numeric(10, 2) can hold
MAX_RESTOCK = 1_000_000
ANALYTICS_DAYS = 30
MAX_RESTOCK_HISTORY = 1000


class ServiceError(Exception):
    status = 400

    def __init__(self, message="", field=None):
        super().__init__(message)
        # The form field at fault, if there is one. The HTML pages use it to mark
        # that field. The API ignores it and sends only the message.
        self.field = field


class ValidationError(ServiceError):
    status = 400


class NotFoundError(ServiceError):
    status = 404


class ConflictError(ServiceError):
    status = 409


# --- small validators -------------------------------------------------------


def _check_fields(data, allowed):
    if not isinstance(data, dict):
        raise ValidationError("request body must be a JSON object")
    unknown = set(data) - allowed
    if unknown:
        raise ValidationError(f"unknown field(s): {', '.join(sorted(unknown))}")


def _text(data, field, max_len, required=True):
    value = data.get(field, "")
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be a string", field)
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{field} is required", field)
    if len(value) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters", field)
    return value


def _int(data, field, minimum, maximum):
    value = data.get(field)
    # bool is a subclass of int in Python, so reject it explicitly.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field} must be a whole number", field)
    if value < minimum or value > maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum}", field)
    return value


def _price(data):
    value = data.get("price")
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        raise ValidationError("price must be a number", "price")
    try:
        price = Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValidationError("price must be a number", "price") from None
    if not price.is_finite() or price < 0 or price > MAX_PRICE:
        raise ValidationError(f"price must be between 0 and {MAX_PRICE}", "price")
    return price


def _sku(data):
    sku = _text(data, "sku", 64)
    if not SKU_PATTERN.match(sku):
        raise ValidationError("sku may only contain letters, digits, '-' and '_'", "sku")
    return sku


def _validate_product(data, partial):
    """Return a dict of clean values. `partial` allows missing fields (PUT)."""
    _check_fields(data, PRODUCT_FIELDS)
    if not partial:
        missing = REQUIRED_PRODUCT_FIELDS - set(data)
        if missing:
            raise ValidationError(f"missing field(s): {', '.join(sorted(missing))}")
    elif not data:
        raise ValidationError("nothing to update")

    clean = {}
    if "name" in data:
        clean["name"] = _text(data, "name", 200)
    if "sku" in data:
        clean["sku"] = _sku(data)
    if "description" in data:
        clean["description"] = _text(data, "description", 2000, required=False)
    if "price" in data:
        clean["price"] = _price(data)
    if "stock_level" in data:
        clean["stock_level"] = _int(data, "stock_level", 0, MAX_STOCK)
    return clean


def _sku_taken(sku, exclude_id=None):
    query = select(Product.id).where(Product.sku == sku)
    if exclude_id is not None:
        query = query.where(Product.id != exclude_id)
    return db.session.execute(query).first() is not None


def _commit_or_conflict():
    """Commit; turn a unique-constraint race into a 409 instead of a 500."""
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ConflictError("a product with this sku already exists", "sku") from None


# --- products ----------------------------------------------------------------


def list_products():
    return db.session.scalars(select(Product).order_by(Product.name)).all()


def get_product(product_id):
    product = db.session.get(Product, product_id)
    if product is None:
        raise NotFoundError("product not found")
    return product


def low_stock_products(threshold):
    query = (
        select(Product)
        .where(Product.stock_level < threshold)
        .order_by(Product.stock_level, Product.name)
    )
    return db.session.scalars(query).all()


def create_product(data):
    clean = _validate_product(data, partial=False)
    if _sku_taken(clean["sku"]):
        raise ConflictError("a product with this sku already exists", "sku")
    product = Product(**clean)
    db.session.add(product)
    _commit_or_conflict()
    return product


def update_product(product_id, data):
    product = get_product(product_id)
    clean = _validate_product(data, partial=True)
    if "sku" in clean and _sku_taken(clean["sku"], exclude_id=product.id):
        raise ConflictError("a product with this sku already exists", "sku")
    for field, value in clean.items():
        setattr(product, field, value)
    _commit_or_conflict()
    return product


def delete_product(product_id):
    product = get_product(product_id)
    db.session.delete(product)  # its restock logs are deleted too (cascade)
    db.session.commit()


def restock_product(product_id, data):
    product = get_product(product_id)
    _check_fields(data, RESTOCK_FIELDS)
    if "quantity" not in data:
        raise ValidationError("missing field(s): quantity", "quantity")
    quantity = _int(data, "quantity", 1, MAX_RESTOCK)
    note = _text(data, "note", 500, required=False)

    product.stock_level += quantity
    log = RestockLog(product=product, quantity=quantity, note=note)
    db.session.add(log)
    db.session.commit()
    return log


def list_restocks():
    query = (
        select(RestockLog)
        .order_by(RestockLog.created_at.desc(), RestockLog.id.desc())
        .limit(MAX_RESTOCK_HISTORY)
    )
    return db.session.scalars(query).all()


def analytics(threshold, today=None):
    """Data for the dashboard chart."""
    products = list_products()
    today = today or datetime.now(UTC).date()
    first_day = today - timedelta(days=ANALYTICS_DAYS - 1)
    since = datetime.combine(first_day, datetime.min.time(), tzinfo=UTC)

    # Count per day in Python, so the same code works on SQLite and Postgres.
    per_day = {first_day + timedelta(days=i): 0 for i in range(ANALYTICS_DAYS)}
    created = db.session.scalars(
        select(RestockLog.created_at).where(RestockLog.created_at >= since)
    )
    for created_at in created:
        day = as_utc(created_at).date()
        if day in per_day:
            per_day[day] += 1

    return {
        "products": [
            {"id": p.id, "name": p.name, "sku": p.sku, "stock_level": p.stock_level}
            for p in products
        ],
        "total_stock": sum(p.stock_level for p in products),
        "low_stock_count": sum(1 for p in products if p.stock_level < threshold),
        "low_stock_threshold": threshold,
        "restocks_per_day": [
            {"date": date.isoformat(day), "count": count} for day, count in per_day.items()
        ],
    }
