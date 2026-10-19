# PointOfSale API

A point-of-sale backend for a small, single-owner agrovet shop in Kenya. It replaces manual record keeping with a phone-first system that tracks stock, sales, credit and profit.

It is built with **FastAPI** and **PostgreSQL**, and is used in production by the shop owner through a Flutter Android app.

- **Live API:** https://pointofsale-api.onrender.com (interactive docs at `/docs`)
- **Mobile app:** [KingN3V/pos_frontend](https://github.com/KingN3V/pos_frontend)

> The API runs on Render's free tier, so the first request after a period of inactivity can take 30-60 seconds while the server wakes up.

---

## Features

- **Authentication:** JWT login, plus password reset by emailed code (8 characters, 15-minute expiry). Registration is closed in production; accounts are created directly in the database.
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
| Auth | JWT (`python-jose`), bcrypt (`passlib`) |
| Email | SMTP (Gmail) for reset codes |
| Exports | `openpyxl` (Excel), `csv` |
| Hosting | Render (API), Neon (database) |
| Backups | Daily automated dumps to Cloudflare R2, restore-tested |

## Project structure

```
PointOfSale/
├── requirements.txt
├── .env                    # not committed
└── pos/
    ├── main.py             # app setup, CORS, router registration
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

Requirements: Python 3.10+ and a PostgreSQL database.

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

`DATABASE_URL` and `SECRET_KEY` are required: the app refuses to start without them, so there are no insecure fallbacks. Tables are created automatically on startup.

Start the server from the project root (the folder that contains `pos/`):

```bash
uvicorn pos.main:app --reload
```

Then open http://localhost:8000/docs.

Because registration is closed, create your first user by inserting a row into `users` with a bcrypt-hashed password:

```bash
python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('your-password'))"
```

## API overview

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/token`, `POST /auth/forgot-password`, `POST /auth/reset-password` |
| Categories | `POST/GET /products/categories` |
| Products | `POST/GET /products/`, `GET/PATCH/DELETE /products/{id}` (DELETE hides the product) |
| Stock | `POST /products/{id}/stock-movement`, `GET /products/{id}/stock-movements` |
| Customers | `POST/GET /customers/`, `GET/PATCH /customers/{id}` |
| Orders | `POST/GET /orders/`, `GET /orders/{id}`, `POST /orders/{id}/cancel` |
| Payments | `POST/GET /orders/{id}/payments` |
| Reports | `GET /reports/sales-summary`, `/top-products`, `/low-stock`, `/outstanding-balances` |

Every endpoint except the auth routes requires a `Bearer` token.

## Design decisions

- **Per-owner data isolation.** Every table with user data has an `owner_id`, and every query filters by it. Any id a client sends (product, category, customer) is checked to exist and belong to the current user, on updates as well as creates.
- **Stock leaves the shelf when the order is created, not when it is paid.** Credit sales are normal in this shop, and stock that has physically left should not still count as available. Cancelling an open order puts the stock back and logs a movement.
- **Concurrency safety.** Products are locked with `SELECT ... FOR UPDATE` while stock is checked and deducted, in id order to avoid deadlocks. Orders are locked when cancelled or paid, so a double tap cannot restore stock twice or overpay an order. Order, items, stock and movements are committed together or not at all.
- **Price and cost snapshots.** `unit_price` and `unit_cost` are copied onto each order item, so later price changes never rewrite past sales or profit. Items sold without a known buying price are counted separately (`units_missing_cost`) instead of being treated as zero cost.
- **Order lifecycle.** `open` becomes `completed` once payments cover the total, or `cancelled` while still open. Payments cannot exceed the remaining balance; change is given separately.
- **Soft delete for products.** Hiding a product keeps historical orders readable.
- **Password reset.** The same response is returned whether or not an email is registered, so the endpoint cannot be used to discover accounts.
- **Neon-friendly connections.** `pool_pre_ping` and `pool_recycle` handle connections that Neon's pooler closes while idle.

## Known limitations and next steps

I'm listing these deliberately; they are the first things I would improve.

- **Money is stored as `Float`.** Rounding is handled explicitly, but `Numeric` or integer cents is the right type.
- **No automated tests yet.** The first ones I would write cover overselling under concurrent orders, a cancel restoring stock exactly once, and overpayment rejection.
- **Checkout is two requests** (create order, then record payment) from the client. A dropped connection between them leaves an open order holding stock. A single transactional endpoint or an idempotency key would remove this.
- **No migrations.** Tables come from `create_all`, which does not alter existing tables. Alembic is the next step once the schema needs to change.
- **Query efficiency.** Some responses and reports issue a query per row. Joins/eager loading and SQL aggregates would fix this, and endpoints should move to plain `def` or an async engine so blocking database calls don't sit in `async def` handlers.
- **Security hardening still to do:** rate limiting on login and reset, reset codes generated with `secrets` instead of `random`, a tighter CORS policy, token refresh, and not returning raw SMTP errors to the client.
- **Time zones.** Timestamps are stored in UTC and the "today" boundary is computed in UTC, so the day rolls over at 3 a.m. Kenya time. Ranges should be computed in `Africa/Nairobi`.
- **M-Pesa STK Push** is planned. Payment methods are currently recorded as `CASH` or `MPESA` and confirmed by the shop owner.

## License

Personal project; no license specified.
