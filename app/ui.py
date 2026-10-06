"""HTML pages (Jinja templates). Every page needs a logged-in session.

Forms POST here; these routes convert the form strings to numbers and call
the same services.py functions as the JSON API. CSRF tokens are checked on
every POST by Flask-WTF's CSRFProtect (set up in __init__.py).
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
    """Read the product form. Values that do not parse are passed on
    unchanged, so services.py rejects them with a clear message."""
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


@bp.get("/")
def dashboard():
    threshold = current_app.config["LOW_STOCK_THRESHOLD"]
    return render_template(
        "dashboard.html",
        products=services.list_products(),
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
            flash(str(exc), "error")
            return render_template("product_form.html", form=form), exc.status
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
    return render_template("product.html", product=product, form=product.to_dict())


@bp.post("/products/<int:product_id>")
def update_product(product_id):
    try:
        services.update_product(product_id, _product_form_data())
    except services.NotFoundError:
        flash("Product not found.", "error")
        return redirect(url_for("ui.dashboard"))
    except services.ServiceError as exc:
        flash(str(exc), "error")
        product = services.get_product(product_id)
        return render_template("product.html", product=product, form=request.form), exc.status
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
