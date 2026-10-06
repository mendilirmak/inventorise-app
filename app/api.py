"""JSON API under /api. Every route needs a bearer token (see auth.py).

The routes only parse the request and shape the response; the rules live in
services.py, shared with the HTML UI.
"""

from flask import Blueprint, current_app, jsonify, request

from . import services
from .auth import require_api_token

bp = Blueprint("api", __name__, url_prefix="/api")
bp.before_request(require_api_token)


@bp.errorhandler(services.ServiceError)
def service_error(exc):
    return jsonify(error=str(exc)), exc.status


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise services.ValidationError("request body must be a JSON object")
    return data


def _threshold():
    return current_app.config["LOW_STOCK_THRESHOLD"]


@bp.get("/products")
def list_products():
    return jsonify([p.to_dict() for p in services.list_products()])


# Route order matters: /low-stock and /analytics are registered BEFORE
# /<int:product_id>. The `int:` converter also means "low-stock" can never
# be mistaken for a product id - without it, /products/low-stock would be
# sent to get_product("low-stock") and return 404.
@bp.get("/products/low-stock")
def low_stock():
    return jsonify([p.to_dict() for p in services.low_stock_products(_threshold())])


@bp.get("/products/analytics")
def analytics():
    return jsonify(services.analytics(_threshold()))


@bp.get("/products/<int:product_id>")
def get_product(product_id):
    return jsonify(services.get_product(product_id).to_dict())


@bp.post("/products")
def create_product():
    product = services.create_product(_json_body())
    return jsonify(product.to_dict()), 201


@bp.put("/products/<int:product_id>")
def update_product(product_id):
    return jsonify(services.update_product(product_id, _json_body()).to_dict())


@bp.delete("/products/<int:product_id>")
def delete_product(product_id):
    services.delete_product(product_id)
    return "", 204


@bp.post("/products/<int:product_id>/restock")
def restock_product(product_id):
    restock = services.restock_product(product_id, _json_body())
    return jsonify({**restock.to_dict(), "stock_level": restock.product.stock_level}), 201


@bp.get("/restocks")
def list_restocks():
    return jsonify([r.to_dict() for r in services.list_restocks()])
