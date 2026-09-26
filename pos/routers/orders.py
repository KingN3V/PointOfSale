from datetime import date, datetime, timedelta
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Orders, OrderItems, Payments, Products, Customers, StockMovements, Users

from ..schemas import (
    OrderCreate, OrderOut,
    PaymentCreate, PaymentOut,
)
from ..auth import get_current_user
from .reports import _csv_response, _excel_response, _validate_format

router = APIRouter(
    prefix="/orders",
    tags=["orders"]
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[Users, Depends(get_current_user)]


def _resolve_optional_date_range(period: Optional[str], start_date: Optional[date], end_date: Optional[date]):
    """Like reports.py's _resolve_date_range, but with no default: if none
    of period/start_date/end_date is given, returns (None, None) meaning
    "no filter" — orders.py's other callers rely on that unfiltered default.
    """
    if period is None and start_date is None and end_date is None:
        return None, None

    if start_date or end_date:
        if not (start_date and end_date):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both start_date and end_date are required for a custom range"
            )
        if start_date > end_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="start_date must be before end_date"
            )
        return (
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date, datetime.max.time())
        )

    today = datetime.utcnow().date()

    if period == "today":
        range_start, range_end = today, today
    elif period == "week":
        range_start, range_end = today - timedelta(days=today.weekday()), today
    elif period == "month":
        range_start, range_end = today.replace(day=1), today
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period must be one of: today, week, month"
        )

    return (
        datetime.combine(range_start, datetime.min.time()),
        datetime.combine(range_end, datetime.max.time())
    )


def _with_extras(db: Session, order: Orders) -> Orders:
    """Attach transient (non-DB) fields the response schema expects."""
    items = (
        db.query(OrderItems)
        .filter(OrderItems.order_id == order.id)
        .all()
    )

    # Attach product_name to each item
    for item in items:
        product = db.query(Products).filter(Products.id == item.product_id).first()
        item.product_name = product.name if product else "Unknown product"

    order.items = items

    paid_so_far = sum(
        p.amount for p in db.query(Payments).filter(Payments.order_id == order.id).all()
    )
    order.balance_due = round(order.total - paid_so_far, 2)

    # Attach customer_name and customer_phone
    if order.customer_id is not None:
        customer = db.query(Customers).filter(Customers.id == order.customer_id).first()
        order.customer_name = customer.name if customer else "Unknown customer"
        order.customer_phone = customer.phone_number if customer else None
    else:
        order.customer_name = None
        order.customer_phone = None

    return order

# ---------- Orders ----------

@router.post("/", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(user: user_dependency, db: db_dependency, order: OrderCreate):
    if not order.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An order must contain at least one item"
        )

    if order.customer_id is not None:
        customer = db.query(Customers).filter(
            Customers.id == order.customer_id,
            Customers.owner_id == user.id
        ).first()
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="customer_id does not exist or does not belong to you"
            )

    # Add up the quantity per product first, so a product listed on two lines
    # is checked against stock as one combined quantity.
    quantities: Dict[int, int] = {}
    for item in order.items:
        if item.quantity <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="quantity must be greater than 0"
            )
        quantities[item.product_id] = quantities.get(item.product_id, 0) + item.quantity

    line_items = []  # (product, quantity, unit_price, unit_cost, subtotal)
    subtotal_total = 0.0

    # Products are locked (FOR UPDATE) while we check stock, so another request
    # cannot sell the same units between our check and our deduction. Locking in
    # id order stops two requests from waiting on each other.
    for product_id in sorted(quantities):
        quantity = quantities[product_id]

        product = db.query(Products).filter(
            Products.id == product_id,
            Products.owner_id == user.id,
            Products.is_active == True
        ).with_for_update().first()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product {product_id} not found, inactive, or does not belong to you"
            )

        if product.stock_quantity < quantity:
            if product.stock_quantity <= 0:
                detail = f"{product.name} is out of stock"
            else:
                detail = f"Only {product.stock_quantity} of {product.name} in stock"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=detail
            )

        item_subtotal = product.price * quantity
        subtotal_total += item_subtotal
        line_items.append(
            (product, quantity, product.price, product.cost_price, item_subtotal)
        )

    new_order = Orders(
        owner_id=user.id,
        customer_id=order.customer_id,
        status="open",
        subtotal=subtotal_total,
        tax_total=0.0,
        total=subtotal_total
    )
    db.add(new_order)
    db.flush()  # assigns new_order.id without committing

    new_order.order_number = f"ORD-{new_order.id:06d}"

    for product, quantity, unit_price, unit_cost, item_subtotal in line_items:
        db.add(OrderItems(
            order_id=new_order.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=unit_price,
            unit_cost=unit_cost,
            subtotal=item_subtotal
        ))

        # Stock leaves the shelf when the order is created, not when it is paid
        product.stock_quantity -= quantity
        db.add(StockMovements(
            product_id=product.id,
            quantity_change=-quantity,
            movement_type="sale",
            note=f"Sale on order {new_order.order_number}"
        ))

    # Order, items, stock and stock movements are saved together or not at all
    db.commit()
    db.refresh(new_order)

    return _with_extras(db, new_order)


@router.get("/", response_model=List[OrderOut])
async def list_orders(
    user: user_dependency,
    db: db_dependency,
    status_filter: Optional[str] = None,
    customer_id: Optional[int] = None,
    q: Optional[str] = Query(None, description="Search by customer name or phone"),
    period: Optional[str] = Query(None, description="today, week, or month"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    format: str = Query("json")
):
    export_format = _validate_format(format)

    query = db.query(Orders).filter(Orders.owner_id == user.id)
    if status_filter:
        query = query.filter(Orders.status == status_filter)
    if customer_id is not None:
        query = query.filter(Orders.customer_id == customer_id)
    if q:
        # Walk-in orders (no customer_id) never match a search — there's
        # no customer to search by.
        like = f"%{q}%"
        query = query.join(Customers, Orders.customer_id == Customers.id).filter(
            (Customers.name.ilike(like)) | (Customers.phone_number.ilike(like))
        )

    # Filters every order by created_at regardless of status, so "today"
    # shows everything that happened today — a credit sale opened today, a
    # sale cancelled today — not just what settled today. No filter is
    # applied at all when period/start_date/end_date are all omitted.
    range_start, range_end = _resolve_optional_date_range(period, start_date, end_date)
    if range_start is not None:
        query = query.filter(
            Orders.created_at >= range_start,
            Orders.created_at <= range_end
        )

    # Newest first. id breaks ties.
    query = query.order_by(Orders.created_at.desc(), Orders.id.desc())

    if export_format != "json":
        # Exports everything matching the current filters, not just the
        # page she happens to have loaded on screen.
        orders = [_with_extras(db, order) for order in query.all()]
        header = [
            "order_number", "created_at", "status", "customer_name",
            "customer_phone", "total", "paid", "balance_due", "items"
        ]
        rows = [
            [
                o.order_number,
                o.created_at.isoformat(),
                o.status,
                o.customer_name or "",
                o.customer_phone or "",
                o.total,
                round(o.total - o.balance_due, 2),
                o.balance_due,
                "; ".join(f"{item.quantity} x {item.product_name}" for item in o.items),
            ]
            for o in orders
        ]
        if export_format == "csv":
            return _csv_response("sales_history", header, rows)
        return _excel_response("sales_history", header, rows)

    orders = query.limit(limit).offset(offset).all()
    return [_with_extras(db, order) for order in orders]


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(user: user_dependency, db: db_dependency, order_id: int):
    order = db.query(Orders).filter(
        Orders.id == order_id,
        Orders.owner_id == user.id
    ).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    return _with_extras(db, order)


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(user: user_dependency, db: db_dependency, order_id: int):
    # The order row is locked so a double tap (or two devices) cannot cancel the
    # same order twice and put its stock back twice.
    order = db.query(Orders).filter(
        Orders.id == order_id,
        Orders.owner_id == user.id
    ).with_for_update().first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel an order with status '{order.status}'"
        )

    # Put the stock back. Restored even if the product was deactivated since,
    # so the count stays right if it is ever reactivated.
    order_items = (
        db.query(OrderItems)
        .filter(OrderItems.order_id == order.id)
        .order_by(OrderItems.product_id)
        .all()
    )
    for order_item in order_items:
        product = db.query(Products).filter(
            Products.id == order_item.product_id
        ).with_for_update().first()
        if not product:
            continue

        product.stock_quantity += order_item.quantity
        db.add(StockMovements(
            product_id=product.id,
            quantity_change=order_item.quantity,
            movement_type="sale_cancelled",
            note=f"Order {order.order_number} cancelled"
        ))

    order.status = "cancelled"
    db.commit()
    db.refresh(order)

    return _with_extras(db, order)


# ---------- Payments ----------

@router.post(
    "/{order_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED
)
async def create_payment(
    user: user_dependency,
    db: db_dependency,
    order_id: int,
    payment: PaymentCreate
):
    # Locked so two payments arriving together cannot both pass the
    # overpayment check below.
    order = db.query(Orders).filter(
        Orders.id == order_id,
        Orders.owner_id == user.id
    ).with_for_update().first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if payment.order_id != order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="order_id in body must match order_id in URL"
        )

    if order.status != "open":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot record a payment against an order with status '{order.status}'"
        )

    if payment.amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="amount must be greater than 0"
        )

    existing_payments = db.query(Payments).filter(Payments.order_id == order_id).all()
    already_paid = sum(p.amount for p in existing_payments)
    remaining_balance = round(order.total - already_paid, 2)

    if payment.amount > remaining_balance + 0.01:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment of {payment.amount} exceeds the remaining balance of "
                   f"{remaining_balance}. Record only the amount applied to the order; "
                   f"give change separately."
        )

    new_total_paid = already_paid + payment.amount

    new_payment = Payments(
        order_id=order_id,
        method=payment.method,
        amount=payment.amount
    )
    db.add(new_payment)

    # Complete the order once payments cover the total.
    # Stock was already deducted when the order was created.
    if new_total_paid >= order.total - 0.01:
        order.status = "completed"
        order.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(new_payment)
    return new_payment


@router.get("/{order_id}/payments", response_model=List[PaymentOut])
async def list_payments(user: user_dependency, db: db_dependency, order_id: int):
    order = db.query(Orders).filter(
        Orders.id == order_id,
        Orders.owner_id == user.id
    ).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    return (
        db.query(Payments)
        .filter(Payments.order_id == order_id)
        .order_by(Payments.created_at.desc())
        .all()
    )