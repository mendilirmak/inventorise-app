# Inventorise — app

A small inventory system for a retail shop. One Flask app serves a JSON API
(`/api/...`) and a simple HTML UI. The data lives in PostgreSQL.

The deployment and pipeline are in the separate
[inventorise-devops](https://github.com/mendilirmak/inventorise-devops) repo.

## Layout

| Path | What it does |
|---|---|
| `app/__init__.py` | Builds the app: logging, security headers, health and metrics routes |
| `app/config.py` | Reads settings from environment variables. Refuses to start if one is wrong |
| `app/models.py` | Database tables: `products`, `restock_logs`, `users` |
| `app/services.py` | Business rules (validation, restock, analytics). Used by the API and the UI |
| `app/auth.py` | Login: browser session and API token |
| `app/api.py` | JSON routes under `/api` |
| `app/ui.py`, `templates/`, `static/` | HTML pages, styles, fonts and the dashboard charts |
| `app/cli.py` | The `flask create-user` command |
| `tests/` | Unit tests. They use in-memory SQLite, so no PostgreSQL is needed |
| `tests/smoke/` | Smoke test, run by the pipeline against the deployed app |

## Diagrams

The application's parts are drawn in
[`docs/diagrams/application.png`](https://github.com/mendilirmak/inventorise-devops/blob/main/docs/diagrams/application.png),
and the tables in
[`docs/diagrams/data-model.png`](https://github.com/mendilirmak/inventorise-devops/blob/main/docs/diagrams/data-model.png)
(both in the devops repo).

## Configuration

Environment variables only. `.env.example` lists them all.

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | e.g. `postgresql+psycopg://user:pass@host:5432/db` |
| `SECRET_KEY` | Signs session cookies. At least 32 characters |
| `APP_ENV` | `dev` or `prod`. `prod` sends cookies over HTTPS only |
| `LOW_STOCK_THRESHOLD` | Products with stock **below** this are "low stock" (default 10) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

## Run locally with Docker Compose

Run these in WSL2 (Ubuntu), not PowerShell.

```bash
cp .env.example .env
# Edit .env and set SECRET_KEY and POSTGRES_PASSWORD. To make a key:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build -d
docker compose exec app flask create-user admin    # asks for a password (12+ characters)
```

Open http://localhost:8000 and log in.

Check that it works:

```bash
curl -s localhost:8000/health/ready     # {"status":"ok"}: the app and the database are up
docker compose logs app | tail          # one JSON line per request
```

There is no sign-up page. Users are created only with `flask create-user`.
Running it again for an existing user sets a new password and cancels that
user's API token.

Stop with `docker compose down`. The data stays in the `pgdata` volume.
`docker compose down -v` deletes the data too.

## Use the API

Every `/api/*` call needs a token. A token is valid for 24 hours.

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"YOUR-PASSWORD"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')

curl -s localhost:8000/api/products -H "Authorization: Bearer $TOKEN"
```

| Method | Path | Body |
|---|---|---|
| GET | `/api/products` | |
| GET | `/api/products/low-stock` | |
| GET | `/api/products/analytics` | |
| GET | `/api/products/<id>` | |
| POST | `/api/products` | `name`, `sku`, `price`, `stock_level`, optional `description` |
| PUT | `/api/products/<id>` | any of the fields above |
| DELETE | `/api/products/<id>` | |
| POST | `/api/products/<id>/restock` | `quantity` (more than 0), optional `note` |
| GET | `/api/restocks` | newest first, last 1000 |

Errors return JSON `{"error": "..."}`: 400 for bad input, 401 for a missing or
expired token, 404 if not found, 409 if the SKU is already used. Unknown
fields are rejected with 400.

Open without a login: `/health/live`, `/health/ready` and `/metrics`.

## Tests and lint

With Python 3.12 in a virtual environment:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check .
pytest
```

Or without installing anything, in the same base image the app uses:

```bash
# The flags keep root-owned cache files out of your folder.
docker run --rm -v "$PWD":/src -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.12.15-slim-trixie \
  sh -c "pip install -q -r requirements-dev.txt && ruff check --no-cache . && pytest -p no:cacheprovider"
```

The smoke test runs only when `BASE_URL` is set:

```bash
BASE_URL=http://localhost:8000 SMOKE_USER=admin SMOKE_PASSWORD=... pytest tests/smoke
```

It adds a product with 3 units and expects it in the low-stock list. So
`LOW_STOCK_THRESHOLD` must be above 3 on the target.

## Design notes

- **Tables** are created at startup with `db.create_all()`. That is enough for
  this project. A real product would use migrations (Alembic), so the schema
  can change without losing data. On Postgres, a lock makes the pods take
  turns, so two pods never create the tables at the same moment.
- **Passwords** are hashed with scrypt. **API tokens** are stored only as
  SHA-256 hashes, so a leaked database gives no usable tokens. Each user has
  one token, and a new login replaces it.
- **The API accepts only bearer tokens, not the browser cookie.** A malicious
  site cannot make your browser call the API (this attack is called CSRF,
  cross-site request forgery). The HTML forms use CSRF tokens instead. The
  dashboard charts get their data in the page, from the same function that the
  analytics API uses.
- **The pages load styles, scripts and fonts only from this site**, except the
  pinned Chart.js file (the Content-Security-Policy allows nothing else). So the
  templates have no inline `style` or `<script>`, and the IBM Plex fonts are
  served from `app/static/fonts/` (see the README there for the source and checksums).
- **The dashboard** lists the products below the low-stock threshold, lowest first,
  with a form to add stock right there. The form sends the one word `next=dashboard`,
  never a URL, so it cannot redirect off the site. The product table is searched and
  sorted in the browser by `static/products-table.js`; without JavaScript it is still
  complete.
- **gunicorn runs one worker with 4 threads per container.** Kubernetes adds
  containers under load. One process per container keeps the Prometheus
  metrics simple.
- **Known gaps** (no login rate limit or lockout, and others) are listed in
  `docs/SECURITY.md` in the devops repo.
