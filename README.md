# Inventorise — app

A small inventory system for a retail chain: a Flask app that serves both a
JSON API (`/api/...`) and a simple HTML UI, backed by PostgreSQL.
Deployment, pipeline and infrastructure live in the separate
[inventorise-devops](https://github.com/mendilirmak/inventorise-devops) repo.

## What is in here

| Path | What it is |
|---|---|
| `app/config.py` | Reads settings from environment variables; refuses to start if one is invalid |
| `app/models.py` | Database tables: `products`, `restock_logs`, `users` |
| `app/services.py` | Business rules (validation, restock, analytics), used by both API and UI |
| `app/auth.py` | Browser login (session cookie) and API login (bearer token) |
| `app/api.py` | JSON routes under `/api` |
| `app/ui.py` + `templates/` | HTML pages |
| `app/cli.py` | `flask create-user` command |
| `tests/` | Unit tests (SQLite in memory, no Postgres needed) |
| `tests/smoke/` | Test run against a deployed app by the pipeline |

## Configuration

Environment variables only (see `.env.example`):

| Variable | Meaning |
|---|---|
| `DATABASE_URL` | e.g. `postgresql+psycopg://user:pass@host:5432/db` |
| `SECRET_KEY` | Signs session cookies. At least 32 characters |
| `APP_ENV` | `dev` or `prod`. `prod` sends cookies over HTTPS only |
| `LOW_STOCK_THRESHOLD` | Products with stock **below** this are "low stock" (default 10) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

## Run it locally (Docker Compose)

Run these inside WSL2 (Ubuntu), not PowerShell.

```bash
cp .env.example .env
# Edit .env: set SECRET_KEY and POSTGRES_PASSWORD. To generate a key:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build -d
docker compose exec app flask create-user admin    # asks for a password (min 12 chars)
```

Open http://localhost:8000 and log in.

**Check it works:**

```bash
curl -s localhost:8000/health/ready            # {"status":"ok"} = app + database OK
docker compose logs app | tail                 # one JSON line per request
```

Users are only ever created this way — there is no registration page.
Running `create-user` again for an existing user changes the password and
cancels that user's API token.

Stop with `docker compose down` (data is kept in the `pgdata` volume;
`docker compose down -v` deletes it).

## Using the API

Every `/api/*` call needs a token. Get one (valid 24 hours):

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
| POST | `/api/products/<id>/restock` | `quantity` (> 0), optional `note` |
| GET | `/api/restocks` | newest first, last 1000 |

Errors are JSON `{"error": "..."}` with 400 (bad input), 401 (no/expired
token), 404 (not found) or 409 (SKU already used). Unknown fields are
rejected with 400.

Open endpoints (no login): `/health/live`, `/health/ready`, `/metrics`.

## Tests and lint

With Python 3.12 and a virtual environment:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check .
pytest
```

Or without installing anything locally, in the same base image the app uses:

```bash
# The flags stop the container (which runs as root) from leaving
# root-owned cache files in your folder.
docker run --rm -v "$PWD":/src -w /src -e PYTHONDONTWRITEBYTECODE=1 python:3.12.15-slim-trixie \
  sh -c "pip install -q -r requirements-dev.txt && ruff check --no-cache . && pytest -p no:cacheprovider"
```

The smoke test runs only when `BASE_URL` is set:

```bash
BASE_URL=http://localhost:8000 SMOKE_USER=admin SMOKE_PASSWORD=... pytest tests/smoke
```

It creates a product with 3 units and expects it in the low-stock list, so
`LOW_STOCK_THRESHOLD` must be above 3 on the target.

## Design notes

- **Tables are created with `db.create_all()` at startup.** Fine for this
  project; a real product would use migrations (Alembic) so the schema can
  change without losing data. On Postgres a database lock stops two pods
  from creating tables at the same moment.
- **Passwords** are hashed with scrypt (`werkzeug.security`). **API tokens**
  are stored only as SHA-256 hashes, so a database leak does not leak
  usable tokens. One active token per user; logging in again replaces it.
- **The API accepts only bearer tokens, not the browser cookie.** That makes
  cross-site request forgery (CSRF: another site making your browser send
  requests) impossible against the API. HTML forms are protected with
  CSRF tokens instead. Because of this the dashboard chart gets its data
  embedded in the page, from the same function `/api/products/analytics`
  uses.
- **gunicorn runs 1 worker with 4 threads per container.** Kubernetes adds
  containers when load grows, and Prometheus metrics stay simple (no
  multi-process mode).
- **Known gaps** (no login rate limiting or lockout, etc.) are listed in
  `docs/SECURITY.md` in the devops repo.
