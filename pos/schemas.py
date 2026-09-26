from datetime import datetime
from typing import List, Optional, Dict

from pydantic import BaseModel, ConfigDict, EmailStr


# ---------- Auth / Token ----------

class Token(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    role: Optional[str] = None


# ---------- Users ----------

class UserCreate(BaseModel):
    email: EmailStr
    username: str
    first_name: str
    last_name: str
    password: str
    role: str
    phone_number: Optional[str] = None


class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    is_active: Optional[bool] = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    username: str
    first_name: str
    last_name: str
    is_active: bool
    role: str
    phone_number: Optional[str] = None


# ---------- Password Resets ----------

class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    reset_token: str
    new_password: str


# ---------- Categories ----------

class CategoryCreate(BaseModel):
    name: str


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


# ---------- Products ----------

class ProductCreate(BaseModel):
    sku: str
    name: str
    description: Optional[str] = None
    category_id: Optional[int] = None
    price: float
    cost_price: Optional[float] = None
    stock_quantity: int = 0


class ProductUpdate(BaseModel):
    sku: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[int] = None
    price: Optional[float] = None
    cost_price: Optional[float] = None
    is_active: Optional[bool] = None


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    description: Optional[str] = None
    category_id: Optional[int] = None
    price: float
    cost_price: Optional[float] = None
    stock_quantity: int
    is_active: bool



# ---------- Customers ----------

class CustomerCreate(BaseModel):
    name: str
    phone_number: Optional[str] = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone_number: Optional[str] = None


# ---------- Order Items ----------

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = 1


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    product_id: int
    product_name: str          # NEW
    quantity: int
    unit_price: float
    subtotal: float


# ---------- Orders ----------

class OrderCreate(BaseModel):
    customer_id: Optional[int] = None
    items: List[OrderItemCreate]


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_number: str
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None    # NEW
    customer_phone: Optional[str] = None   # NEW
    status: str
    subtotal: float
    tax_total: float
    total: float
    balance_due: float
    created_at: datetime
    completed_at: Optional[datetime] = None
    items: List[OrderItemOut] = []


# ---------- Payments ----------

class PaymentCreate(BaseModel):
    order_id: int
    method: str
    amount: float


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    method: str
    amount: float
    created_at: datetime


# ---------- Stock Movements ----------

class StockMovementCreate(BaseModel):
    product_id: int
    quantity_change: int
    movement_type: str
    note: Optional[str] = None


class StockMovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    quantity_change: int
    movement_type: str
    note: Optional[str] = None
    created_at: datetime



# ---------- Reports ----------

class SalesSummaryOut(BaseModel):
    range_start: datetime
    range_end: datetime
    order_count: int
    total_revenue: float
    total_profit: float          # only from items sold with a known buying price
    units_missing_cost: int      # units sold with no buying price recorded
    revenue_by_method: Dict[str, float]


class TopProductOut(BaseModel):
    product_id: int
    name: str
    quantity_sold: int
    revenue: float
    profit: float                # only from units sold with a known buying price
    units_missing_cost: int


class LowStockOut(BaseModel):
    product_id: int
    sku: str
    name: str
    stock_quantity: int


class OutstandingBalanceOut(BaseModel):
    customer_id: int
    customer_name: str
    phone_number: Optional[str] = None
    total_balance_due: float
    open_order_count: int