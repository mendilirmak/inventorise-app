"""Tests for the HTML pages: the dashboard, product forms and the restock list."""

import re

import pytest

from app import services
from tests.conftest import PASSWORD, USERNAME, product_payload


@pytest.fixture
def browser(client):
    """A test client that is logged in through the login form."""
    client.post("/login", data={"username": USERNAME, "password": PASSWORD})
    return client


def create(browser, **changes):
    """Create a product through the form. Returns its page URL."""
    response = browser.post("/products/new", data=product_payload(**changes))
    assert response.status_code == 302
    return response.headers["Location"]


def test_dashboard_lists_low_stock_products_lowest_first(browser):
    create(browser, name="Plenty", sku="PLENTY", stock_level=50)
    create(browser, name="Few", sku="FEW", stock_level=4)
    create(browser, name="Almost out", sku="ALMOST-OUT", stock_level=1)

    html = browser.get("/").get_data(as_text=True)

    restock_section = html.split('aria-labelledby="restock-h"')[1].split("</section>")[0]
    assert "Needs restocking" in html
    assert restock_section.index("Almost out") < restock_section.index("Few")
    assert "Plenty" not in restock_section
    assert "1 left" in restock_section


def test_dashboard_without_low_stock_says_so(browser):
    create(browser, stock_level=50)
    html = browser.get("/").get_data(as_text=True)
    assert "Every product has at least 10 units." in html


def test_dashboard_with_no_products_still_renders(browser):
    response = browser.get("/")
    assert response.status_code == 200
    assert "Add the first one" in response.get_data(as_text=True)


def test_restock_from_the_dashboard_returns_to_the_dashboard(browser):
    product_url = create(browser, stock_level=2)
    response = browser.post(f"{product_url}/restock", data={"quantity": "5", "next": "dashboard"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert b"7 units in stock" in browser.get(product_url).data


@pytest.mark.parametrize(
    "next_value", ["https://evil.example/", "//evil.example", "/login", "", "Dashboard"]
)
def test_restock_next_accepts_only_the_word_dashboard(browser, next_value):
    """The form must never redirect anywhere else, so it cannot send people off the site."""
    product_url = create(browser, stock_level=2)
    response = browser.post(f"{product_url}/restock", data={"quantity": "5", "next": next_value})
    assert response.status_code == 302
    assert response.headers["Location"] == product_url


def test_duplicate_sku_marks_the_sku_field(browser):
    create(browser, sku="TAKEN")
    response = browser.post("/products/new", data=product_payload(name="Other", sku="TAKEN"))
    html = response.get_data(as_text=True)

    assert response.status_code == 409
    assert re.search(r'<input id="f-sku"[^>]*aria-invalid="true"', html)
    assert 'class="field-error" id="e-sku"' in html
    assert "A product with this sku already exists" in html  # first letter capitalised
    assert 'value="Other"' in html  # the other values are kept


def test_bad_price_marks_only_the_price_field(browser):
    response = browser.post("/products/new", data=product_payload(price="-5"))
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert 'id="e-price"' in html
    assert 'id="e-sku"' not in html


def test_edit_form_shows_the_price_with_two_decimals(browser):
    product_url = create(browser, price="549")
    assert 'value="549.00"' in browser.get(product_url).get_data(as_text=True)


def test_delete_needs_a_second_step_but_still_works(browser):
    product_url = create(browser)
    page = browser.get(product_url).get_data(as_text=True)
    assert "<details>" in page  # the confirmation step
    assert "It cannot be undone." in page
    assert browser.post(f"{product_url}/delete").status_code == 302
    assert browser.get(product_url).status_code == 302  # product is gone: back to the dashboard


@pytest.mark.parametrize("path", ["/login", "/", "/products/new"])
def test_pages_use_no_inline_style_or_script(browser, path):
    """The Content-Security-Policy forbids both, so a template that used one would break."""
    html = browser.get(path).get_data(as_text=True)
    assert not re.search(r"<[^>]+\sstyle=", html)
    assert "<style" not in html
    for script in re.findall(r"<script\b([^>]*)>", html):
        assert "src=" in script or 'type="application/json"' in script
    assert not re.search(r"<[^>]+\son(click|load|change|submit)=", html)


def test_static_files_are_served_without_login(client):
    for path in [
        "/static/style.css",
        "/static/favicon.svg",
        "/static/fonts/plex-sans-400.woff2",
        "/static/fonts/plex-sans-600.woff2",
        "/static/fonts/plex-mono-400.woff2",
    ]:
        assert client.get(path).status_code == 200, path


def test_validation_errors_carry_the_field_for_the_pages_but_not_for_the_api(api):
    with pytest.raises(services.ValidationError) as caught:
        services.create_product(product_payload(price="abc"))
    assert caught.value.field == "price"

    response = api.post("/api/products", json=product_payload(price="abc"))
    assert response.status_code == 400
    assert response.get_json() == {"error": "price must be a number"}
