# PointOfSale API

A point-of-sale backend for a small, single-owner agrovet shop in Kenya. It replaces manual record keeping with a phone-first system that tracks stock, sales, credit and profit.

It is built with **FastAPI** and **PostgreSQL**, and is used in production by the shop owner through a Flutter Android app.

- **Live API:** https://pointofsale-api.onrender.com (interactive docs at `/docs`)
- **Mobile app:** [KingN3V/pos_frontend](https://github.com/KingN3V/pos_frontend)

> The API runs on Render's free tier, so the first request after a period of inactivity can take 30-60 seconds while the server wakes up.

---

## Features

- **Authentication:** JWT login with rate limiting, plus password reset by emailed code (8 characters, 15-minute expiry). Registration is closed in production; accounts are created directly in the database.
- **Products and categories:** SKU uniqueness per owner, buying and selling prices, soft delete (hide/unhide) so past sales keep their product names.
- **Stock tracking:** every change to stock goes through an auditable `stock_movements` log (initial stock, restock, sale, cancelled sale, expired, damaged, correction). Stock can never go negative.
- **Orders and payments:** multi-item orders, walk-in or customer sales, partial payments, credit sales, cancellation of open orders (stock goes back), and rejection of overpayment.
- **Customers:** create, search and update; outstanding balances per customer.
- **Reports:** sales summary (revenue, profit, revenue by payment method), top products, low stock, outstanding balances. All support `period=today|week|month` or a custom date range, and export as JSON, CSV or Excel.
- **Sales history:** filter by status, customer, search text and date range, with pagination and CSV/Excel export.

## Tech stack

| Area | Choice |
|---|---|
| Framework | FastAPI, Pydantic v2 |
| ORM / DB | SQLAlchemy 2, PostgreSQL (Neon) |
| Migrations | Alembic |
| Auth | JWT (`python-jose`), bcrypt (`passlib`) |
| Email | SMTP (Gmail) for reset codes |
| Exports | `openpyxl` (Excel), `csv` |
| Testing | pytest, against a separate local PostgreSQL test database |
| Hosting | Render (API), Neon (database) |
| Backups | Daily automated dumps to Cloudflare R2, restore-tested |

## Project structure

```
PointOfSale/
├── requirements.txt        # what the deployed app needs
├── requirements-dev.txt    # adds pytest and httpx for running the tests
├── alembic.ini             # Alembic settings (no database URL in it)
├── pytest.ini              # pytest settings
├── .env                    # not committed
├── alembic/
│   ├── env.py              # reads DATABASE_URL, refuses Neon unless told otherwise
│   └── versions/           # migration files, starting with 0001_baseline.py
├── tests/
│   ├── conftest.py         # test database guard, migrations, fixtures
│   ├── test_smoke.py
│   ├── test_payments.py    # overpayment, split and invalid payments
│   ├── test_cancel.py      # cancelling restores stock exactly once
│   ├── test_race.py        # concurrent orders and cancels
│   ├── test_auth.py        # login and rate limits
│   └── test_migrations.py  # fails if models.py and the migrations disagree
└── pos/
    ├── main.py             # app setup, CORS, rate limiting, router registration
    ├── limiter.py          # shared rate limiter (slowapi)
    ├── database.py         # engine and session (pool_pre_ping for Neon)
    ├── models.py           # SQLAlchemy models
    ├── schemas.py          # Pydantic request/response schemas
    ├── auth.py             # password hashing, JWT, get_current_user
    ├── email_service.py    # password reset email
    └── routers/
        ├── auth.py         # /auth: login, forgot/reset password
        ├── products.py     # /products: products, categories, stock movements
        ├── orders.py       # /orders: orders, payments, cancellation
        ├── customers.py    # /customers
        └── reports.py      # /reports
```

## Running locally

Requirements: a recent Python 3 (developed on 3.14.4) and a PostgreSQL database.

```bash
git clone https://github.com/KingN3V/PointOfSale.git
cd PointOfSale
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/posdb
SECRET_KEY=generate-a-long-random-string
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Only needed for password reset emails
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USERNAME=you@example.com
SMTP_PASSWORD=your-app-password
```

`DATABASE_URL` and `SECRET_KEY` are required: the app refuses to start without them, so there are no insecure fallbacks.

The app no longer creates tables on startup; the schema is managed with Alembic. Create the tables in a new, empty database with:

```bash
alembic upgrade head
```

If your database already has the tables from an earlier version (they were created by `create_all`), mark it as up to date instead, without changing any data:

```bash
alembic stamp head
```

Alembic reads `DATABASE_URL` from `.env` and prints which database it is aimed at before it does anything.

Start the server from the project root (the folder that contains `pos/`):

```bash
uvicorn pos.main:app --reload
```

Then open http://localhost:8000/docs.

Because registration is closed, create your first user by inserting a row into `users` with a bcrypt-hashed password:

```bash
python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('your-password'))"
```

## Running the tests

The tests run against a separate local PostgreSQL database, never against the production database. They need real PostgreSQL, not SQLite, because the concurrency tests depend on `SELECT ... FOR UPDATE` row locks.

Create the test database, then add its URL to `.env`:

```bash
psql -U postgres -c 'CREATE DATABASE pos_test;'
```

```env
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/pos_test
```

Install the test tools and run the suite from the project root:

```bash
pip install -r requirements-dev.txt
pytest
```

**Safety guard.** `tests/conftest.py` refuses to run unless `TEST_DATABASE_URL` points at `localhost` and the database name ends in `_test`. Every test starts by emptying all tables in that database, so the guard is what keeps the tests away from real data. The test database is built from the Alembic migrations, so the suite also checks that the migrations produce a working schema.

**What is covered:**

- Payments: overpayment is rejected, including split payments that add up to more than the total, along with zero and negative amounts.
- Cancelling an order puts its stock back exactly once and logs a single `sale_cancelled` movement; a completed order cannot be cancelled.
- Concurrency: simultaneous orders for the last unit (exactly one succeeds), more orders than stock, and simultaneous cancels of the same order. These were verified to fail when the row locks are removed.
- Login, forgot-password and their rate limits.
- Migration drift: a test fails if `models.py` has changes that no migration covers.

## Changing the schema

The database schema is managed with Alembic. The first migration, `0001_baseline`, describes the schema that production had when migrations were introduced. When you change `models.py`, write a migration for it:

```bash
# 1. Edit pos/models.py, then generate a migration from the difference.
#    Run this against a local database that is already up to date (alembic upgrade head).
alembic revision --autogenerate -m "describe the change"

# 2. Read the generated file in alembic/versions/ and fix anything it got wrong.
#    Autogenerate cannot detect renames (it sees a drop plus an add) or server defaults.

# 3. Apply it locally and run the tests.
alembic upgrade head
pytest
```

`tests/test_migrations.py` fails if `models.py` and the migrations disagree, so a forgotten migration is caught by the test suite.

**Applying a migration to production.** Migrations are not run automatically when the app is deployed; run them by hand, after taking a fresh backup. `alembic/env.py` refuses to run against a Neon host unless the command explicitly says so, which makes a mistaken run against production hard to do by accident. Pass the production URL (the direct connection, not the pooled one) for that one command only, and never save it in `.env` or in a file:

```bash
read -rs -p "Production DATABASE_URL: " PROD_URL; echo
DATABASE_URL="$PROD_URL" ALEMBIC_ALLOW_PRODUCTION=1 alembic upgrade head
unset PROD_URL
```

Apply the migration before deploying code that depends on it, for example a new column. Do not edit a migration after it has been applied to production; write a new one instead. The baseline migration cannot be downgraded, because that would delete every table.

## API overview

| Area | Endpoints |
|---|---|
| Health | `GET /`, `GET /healthy` |
| Auth | `POST /auth/token`, `POST /auth/forgot-password`, `POST /auth/reset-password` |
| Categories | `POST/GET /products/categories` |
| Products | `POST/GET /products/`, `GET/PATCH/DELETE /products/{id}` (DELETE hides the product) |
| Stock | `POST /products/{id}/stock-movement`, `GET /products/{id}/stock-movements` |
| Customers | `POST/GET /customers/`, `GET/PATCH /customers/{id}` |
| Orders | `POST/GET /orders/`, `GET /orders/{id}`, `POST /orders/{id}/cancel` |
| Payments | `POST/GET /orders/{id}/payments` |
| Reports | `GET /reports/sales-summary`, `/top-products`, `/low-stock`, `/outstanding-balances` |

Every endpoint requires a `Bearer` token except the auth routes and the health checks (`/` and `/healthy`).

## Design decisions

- **Per-owner data isolation.** Every table with user data has an `owner_id`, and every query filters by it. Any id a client sends (product, category, customer) is checked to exist and belong to the current user, on updates as well as creates.
- **Stock leaves the shelf when the order is created, not when it is paid.** Credit sales are normal in this shop, and stock that has physically left should not still count as available. Cancelling an open order puts the stock back and logs a movement.
- **Concurrency safety.** Routes are plain `def`, so FastAPI runs each request in a worker thread and a slow database call only holds up its own request. Because requests can overlap, correctness comes from the database: products are locked with `SELECT ... FOR UPDATE` while stock is checked and deducted (and when stock movements are logged), in id order to avoid deadlocks. Orders are locked when cancelled or paid, so a double tap cannot restore stock twice or overpay an order. Order, items, stock and movements are committed together or not at all. Tests run simultaneous requests against a real PostgreSQL database to check this, and were verified to fail when the locks are removed.
- **Price and cost snapshots.** `unit_price` and `unit_cost` are copied onto each order item, so later price changes never rewrite past sales or profit. Items sold without a known buying price are counted separately (`units_missing_cost`) instead of being treated as zero cost.
- **Order lifecycle.** `open` becomes `completed` once payments cover the total, or `cancelled` while still open. Payments cannot exceed the remaining balance; change is given separately.
- **Soft delete for products.** Hiding a product keeps historical orders readable.
- **Neon-friendly connections.** `pool_pre_ping` and `pool_recycle` handle connections that Neon's pooler closes while idle.
- **No account enumeration.** Password reset returns the same response whether or not an email is registered, including when sending the email fails (the failure is logged server-side, not returned).

## Known limitations and next steps

I'm listing these deliberately; they are the first things I would improve.

- **Money is stored as `Float`.** Rounding is handled explicitly, but `Numeric` or integer cents is the right type. Until then, the payment checks allow a one-cent tolerance to absorb float noise: a payment up to one cent over the balance is accepted (leaving a balance of -0.01), and an order is completed once it is within one cent of fully paid.
- **Test coverage is focused, not complete.** The tests cover payments, cancellation, stock under concurrent requests, login and rate limits, and migration drift. Reports, CSV/Excel exports, customers, and most product and stock-movement endpoints have no tests yet.
- **Checkout is two requests** (create order, then record payment) from the client. A dropped connection between them leaves an open order holding stock. A single transactional endpoint or an idempotency key would remove this.
- **Migrations are applied by hand.** Alembic manages the schema, but nothing runs a migration on deploy, so each one has to be applied to production manually after a backup.
- **Query efficiency.** Some responses and reports issue a query per row. Joins/eager loading and SQL aggregates would fix this.
- **Token refresh and ongoing security hardening.** Access tokens expire after 60 minutes and there is no refresh flow yet.
- **Time zones.** Timestamps are stored in UTC and the "today" boundary is computed in UTC, so the day rolls over at 3 a.m. Kenya time. Ranges should be computed in `Africa/Nairobi`.
- **M-Pesa STK Push** is planned. Payment methods are currently recorded as `CASH` or `MPESA` and confirmed by the shop owner.

## License

Personal project; no license specified.
