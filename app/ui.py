"""HTML pages (Jinja templates). Every page needs a login.

Forms POST here. The routes turn the form text into numbers and call the same
services.py functions as the JSON API. Flask-WTF checks the CSRF token on
every POST (set up in __init__.py).
"""

from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from . import services

bp = Blueprint("ui", __name__)


@bp.before_request
@login_required
def require_login():
    """Runs before every route in this blueprint; redirects to /login if needed."""


def _product_form_data():
    """Read the product form. Values that do not parse stay as text, so
    services.py rejects them with a clear message."""
    data = {field: request.form.get(field, "") for field in services.PRODUCT_FIELDS}
    try:
        data["stock_level"] = int(data["stock_level"])
    except ValueError:
        pass
    try:
        data["price"] = Decimal(data["price"])
    except InvalidOperation:
        pass
    return data


def _form_error(exc):
    """Template values for a rejected form. A message tied to one field is shown
    next to that field. Any other message goes to the banner at the top."""
    message = str(exc)[:1].upper() + str(exc)[1:]  # the API messages start in lower case
    if exc.field:
        return {"error_field": exc.field, "error_message": message}
    flash(message, "error")
    return {"error_field": None, "error_message": None}


@bp.get("/")
def dashboard():
    threshold = current_app.config["LOW_STOCK_THRESHOLD"]
    return render_template(
        "dashboard.html",
        products=services.list_products(),
        low_products=services.low_stock_products(threshold),
        threshold=threshold,
        # Same data as GET /api/products/analytics, embedded in the page:
        # the API only accepts bearer tokens, not the browser session.
        analytics=services.analytics(threshold),
    )


@bp.route("/products/new", methods=["GET", "POST"])
def new_product():
    form = {}
    if request.method == "POST":
        form = request.form
        try:
            product = services.create_product(_product_form_data())
        except services.ServiceError as exc:
            return render_template("product_form.html", form=form, **_form_error(exc)), exc.status
        flash(f"Created {product.name}.", "info")
        return redirect(url_for("ui.product_page", product_id=product.id))
    return render_template("product_form.html", form=form)


@bp.get("/products/<int:product_id>")
def product_page(product_id):
    try:
        product = services.get_product(product_id)
    except services.NotFoundError:
        flash("Product not found.", "error")
        return redirect(url_for("ui.dashboard"))
    form = product.to_dict()
    form["price"] = f"{product.price:.2f}"  # 549.00, not 549.0
    return render_template("product.html", product=product, form=form)


@bp.post("/products/<int:product_id>")
def update_product(product_id):
    try:
        services.update_product(product_id, _product_form_data())
    except services.NotFoundError:
        flash("Product not found.", "error")
        return redirect(url_for("ui.dashboard"))
    except services.ServiceError as exc:
        product = services.get_product(product_id)
        return (
            render_template("product.html", product=product, form=request.form, **_form_error(exc)),
            exc.status,
        )
    flash("Saved.", "info")
    return redirect(url_for("ui.product_page", product_id=product_id))


@bp.post("/products/<int:product_id>/restock")
def restock_product(product_id):
    data = {"quantity": request.form.get("quantity", ""), "note": request.form.get("note", "")}
    try:
        data["quantity"] = int(data["quantity"])
    except ValueError:
        pass
    try:
        restock = services.restock_product(product_id, data)
    except services.NotFoundError:
        flash("Product not found.", "error")
        return redirect(url_for("ui.dashboard"))
    except services.ServiceError as exc:
        flash(str(exc), "error")
    else:
        flash(f"Added {restock.quantity} units.", "info")
    # The restock list on the dashboard sends next=dashboard. Only this one fixed
    # word is accepted, never a URL, so the form cannot redirect off the site.
    if request.form.get("next") == "dashboard":
        return redirect(url_for("ui.dashboard"))
    return redirect(url_for("ui.product_page", product_id=product_id))


@bp.post("/products/<int:product_id>/delete")
def delete_product(product_id):
    try:
        services.delete_product(product_id)
    except services.NotFoundError:
        flash("Product not found.", "error")
    else:
        flash("Product deleted.", "info")
    return redirect(url_for("ui.dashboard"))
