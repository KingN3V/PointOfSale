import csv
import io
from datetime import date, datetime, timedelta
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from openpyxl import Workbook

from ..database import get_db
from ..models import Orders, OrderItems, Payments, Products, Customers, Users
from ..schemas import (
    SalesSummaryOut, TopProductOut, LowStockOut, OutstandingBalanceOut,
)
from ..auth import get_current_user

router = APIRouter(
    prefix="/reports",
    tags=["reports"]
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[Users, Depends(get_current_user)]


# ---------- Helpers ----------

def _resolve_date_range(period: Optional[str], start_date: Optional[date], end_date: Optional[date]):
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
    period = period or "today"

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


def _order_balance_due(db: Session, order: Orders) -> float:
    paid = sum(p.amount for p in db.query(Payments).filter(Payments.order_id == order.id).all())
    return round(order.total - paid, 2)


def _validate_format(export_format: str) -> str:
    if export_format not in ("json", "csv", "excel"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="format must be one of: json, csv, excel"
        )
    return export_format


def _csv_response(filename: str, header: List[str], rows: List[list]) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"}
    )


def _excel_response(filename: str, header: List[str], rows: List[list]) -> StreamingResponse:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}.xlsx"}
    )


# ---------- Sales Summary ----------

@router.get("/sales-summary")
async def sales_summary(
    user: user_dependency,
    db: db_dependency,
    period: Optional[str] = Query(None, description="today, week, or month"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    format: str = Query("json")
):
    export_format = _validate_format(format)
    range_start, range_end = _resolve_date_range(period, start_date, end_date)

    orders = db.query(Orders).filter(
        Orders.owner_id == user.id,
        Orders.status == "completed",
        Orders.completed_at >= range_start,
        Orders.completed_at <= range_end
    ).all()

    order_count = len(orders)
    total_revenue = round(sum(o.total for o in orders), 2)

    revenue_by_method: Dict[str, float] = {}
    for order in orders:
        for p in db.query(Payments).filter(Payments.order_id == order.id).all():
            revenue_by_method[p.method] = round(revenue_by_method.get(p.method, 0.0) + p.amount, 2)

    # Profit counts only items that had a buying price when they were sold
    total_profit = 0.0
    units_missing_cost = 0
    order_ids = [o.id for o in orders]
    if order_ids:
        for item in db.query(OrderItems).filter(OrderItems.order_id.in_(order_ids)).all():
            if item.unit_cost is None:
                units_missing_cost += item.quantity
            else:
                total_profit += item.subtotal - item.unit_cost * item.quantity
    total_profit = round(total_profit, 2)

    result = SalesSummaryOut(
        range_start=range_start,
        range_end=range_end,
        order_count=order_count,
        total_revenue=total_revenue,
        total_profit=total_profit,
        units_missing_cost=units_missing_cost,
        revenue_by_method=revenue_by_method
    )

    if export_format == "json":
        return result

    header = [
        "order_count", "total_revenue", "total_profit",
        "units_missing_cost", "payment_method", "amount"
    ]
    rows = (
        [
            [order_count, total_revenue, total_profit, units_missing_cost, method, amount]
            for method, amount in revenue_by_method.items()
        ]
        or [[order_count, total_revenue, total_profit, units_missing_cost, "", ""]]
    )

    if export_format == "csv":
        return _csv_response("sales_summary", header, rows)
    return _excel_response("sales_summary", header, rows)

# ---------- Top Products ----------

@router.get("/top-products")
async def top_products(
    user: user_dependency,
    db: db_dependency,
    period: Optional[str] = Query(None, description="today, week, or month"),
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    limit: int = 10,
    format: str = Query("json")
):
    export_format = _validate_format(format)
    range_start, range_end = _resolve_date_range(period, start_date, end_date)

    order_ids = [
        o.id for o in db.query(Orders).filter(
            Orders.owner_id == user.id,
            Orders.status == "completed",
            Orders.completed_at >= range_start,
            Orders.completed_at <= range_end
        ).all()
    ]

    totals: Dict[int, Dict[str, float]] = {}
    if order_ids:
        for item in db.query(OrderItems).filter(OrderItems.order_id.in_(order_ids)).all():
            entry = totals.setdefault(
                item.product_id,
                {"quantity": 0, "revenue": 0.0, "profit": 0.0, "missing": 0}
            )
            entry["quantity"] += item.quantity
            entry["revenue"] += item.subtotal
            if item.unit_cost is None:
                entry["missing"] += item.quantity
            else:
                entry["profit"] += item.subtotal - item.unit_cost * item.quantity

    results = []
    for product_id, data in totals.items():
        product = db.query(Products).filter(Products.id == product_id).first()
        results.append(TopProductOut(
            product_id=product_id,
            name=product.name if product else "Unknown product",
            quantity_sold=int(data["quantity"]),
            revenue=round(data["revenue"], 2),
            profit=round(data["profit"], 2),
            units_missing_cost=int(data["missing"])
        ))

    results.sort(key=lambda r: r.quantity_sold, reverse=True)
    results = results[:limit]

    if export_format == "json":
        return results

    header = ["product_id", "name", "quantity_sold", "revenue", "profit", "units_missing_cost"]
    rows = [
        [r.product_id, r.name, r.quantity_sold, r.revenue, r.profit, r.units_missing_cost]
        for r in results
    ]

    if export_format == "csv":
        return _csv_response("top_products", header, rows)
    return _excel_response("top_products", header, rows)

    


# ---------- Low Stock ----------

@router.get("/low-stock")
async def low_stock(
    user: user_dependency,
    db: db_dependency,
    threshold: int = 5,
    format: str = Query("json")
):
    export_format = _validate_format(format)

    products = db.query(Products).filter(
        Products.owner_id == user.id,
        Products.is_active == True,
        Products.stock_quantity <= threshold
    ).order_by(Products.stock_quantity.asc()).all()

    results = [
        LowStockOut(product_id=p.id, sku=p.sku, name=p.name, stock_quantity=p.stock_quantity)
        for p in products
    ]

    if export_format == "json":
        return results

    header = ["product_id", "sku", "name", "stock_quantity"]
    rows = [[r.product_id, r.sku, r.name, r.stock_quantity] for r in results]

    if export_format == "csv":
        return _csv_response("low_stock", header, rows)
    return _excel_response("low_stock", header, rows)


# ---------- Outstanding Balances ----------

@router.get("/outstanding-balances")
async def outstanding_balances(
    user: user_dependency,
    db: db_dependency,
    q: Optional[str] = None,
    format: str = Query("json")
):
    export_format = _validate_format(format)

    open_orders = db.query(Orders).filter(
        Orders.owner_id == user.id,
        Orders.status == "open",
        Orders.customer_id.isnot(None)
    ).all()

    totals: Dict[int, Dict] = {}
    for order in open_orders:
        balance = _order_balance_due(db, order)
        if balance <= 0:
            continue
        entry = totals.setdefault(order.customer_id, {"balance": 0.0, "order_count": 0})
        entry["balance"] += balance
        entry["order_count"] += 1

    results = []
    for customer_id, data in totals.items():
        customer = db.query(Customers).filter(Customers.id == customer_id).first()
        results.append(OutstandingBalanceOut(
            customer_id=customer_id,
            customer_name=customer.name if customer else "Unknown customer",
            phone_number=customer.phone_number if customer else None,
            total_balance_due=round(data["balance"], 2),
            open_order_count=data["order_count"]
        ))

    if q:
        needle = q.lower()
        results = [
            r for r in results
            if needle in r.customer_name.lower()
            or (r.phone_number and needle in r.phone_number.lower())
        ]

    results.sort(key=lambda r: r.total_balance_due, reverse=True)

    if export_format == "json":
        return results

    header = ["customer_id", "customer_name", "phone_number", "total_balance_due", "open_order_count"]
    rows = [
        [r.customer_id, r.customer_name, r.phone_number, r.total_balance_due, r.open_order_count]
        for r in results
    ]

    if export_format == "csv":
        return _csv_response("outstanding_balances", header, rows)
    return _excel_response("outstanding_balances", header, rows)