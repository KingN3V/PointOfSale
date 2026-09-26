from .database import Base
from sqlalchemy import Column, ForeignKey, Integer, String, Float, Boolean, DateTime
from datetime import datetime



class Users(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True)
    username = Column(String, unique=True)
    first_name = Column(String)
    last_name = Column(String)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)
    role = Column(String)
    phone_number = Column(String)


class PasswordResets(Base):
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    reset_token = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    used = Column(Boolean, default=False)


class Categories(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)


class Products(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    sku = Column(String)
    name = Column(String)
    description = Column(String)
    category_id = Column(Integer, ForeignKey("categories.id"))
    price = Column(Float)
    cost_price = Column(Float)  # buying price; NULL = not set yet
    stock_quantity = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)


class Customers(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    phone_number = Column(String)


class Orders(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    order_number = Column(String, unique=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    status = Column(String, default="open")
    subtotal = Column(Float, default=0.0)
    tax_total = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)


class OrderItems(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer, default=1)
    unit_price = Column(Float)
    unit_cost = Column(Float)  # buying price when the order was placed; NULL = unknown
    subtotal = Column(Float)


class Payments(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    method = Column(String)
    amount = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class StockMovements(Base):
    __tablename__ = "stock_movements"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity_change = Column(Integer)
    movement_type = Column(String)
    note = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)