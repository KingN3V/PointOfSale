from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Customers, Users
from ..schemas import CustomerCreate, CustomerOut
from ..auth import get_current_user

router = APIRouter(
    prefix="/customers",
    tags=["customers"]
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[Users, Depends(get_current_user)]


@router.post("/", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(user: user_dependency, db: db_dependency, customer: CustomerCreate):
    if customer.phone_number:
        existing = db.query(Customers).filter(
            Customers.phone_number == customer.phone_number,
            Customers.owner_id == user.id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A customer with that phone number already exists"
            )

    new_customer = Customers(**customer.model_dump(), owner_id=user.id)
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)
    return new_customer


@router.get("/", response_model=List[CustomerOut])
async def list_customers(user: user_dependency, db: db_dependency, q: Optional[str] = None):
    query = db.query(Customers).filter(Customers.owner_id == user.id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Customers.name.ilike(like)) | (Customers.phone_number.ilike(like))
        )
    return query.all()

@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(user: user_dependency, db: db_dependency, customer_id: int):
    customer = db.query(Customers).filter(
        Customers.id == customer_id,
        Customers.owner_id == user.id
    ).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    user: user_dependency,
    db: db_dependency,
    customer_id: int,
    customer_update: CustomerCreate
):
    customer = db.query(Customers).filter(
        Customers.id == customer_id,
        Customers.owner_id == user.id
    ).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    update_data = customer_update.model_dump(exclude_unset=True)

    if "phone_number" in update_data and update_data["phone_number"] != customer.phone_number:
        existing = db.query(Customers).filter(
            Customers.phone_number == update_data["phone_number"],
            Customers.owner_id == user.id,
            Customers.id != customer_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A customer with that phone number already exists"
            )

    for field, value in update_data.items():
        setattr(customer, field, value)

    db.commit()
    db.refresh(customer)
    return customer