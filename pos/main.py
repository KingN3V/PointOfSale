from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .database import engine, Base
from . import models
from .limiter import limiter
from .routers import auth, products, orders, customers, reports

app = FastAPI(title="POS System")

Base.metadata.create_all(bind=engine)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# The Android app doesn't use CORS (only browsers enforce it), so this only
# needs to allow the API's own /docs page.
origins = ["https://pointofsale-api.onrender.com"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "POS System API is running"}

@app.get("/healthy")
def health():
    return {"status": "Healthy"}


app.include_router(auth.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(customers.router)
app.include_router(reports.router)