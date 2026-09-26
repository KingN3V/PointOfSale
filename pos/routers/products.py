from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Products, Categories, StockMovements, Users
from ..schemas import (
    ProductCreate, ProductUpdate, ProductOut,
    CategoryCreate, CategoryOut,
    StockMovementCreate, StockMovementOut,
)
from ..auth import get_current_user


router = APIRouter(
    prefix="/products",
    tags=["products"]
)

db_dependency = Annotated[Session, Depends(get_db)]
user_dependency = Annotated[Users, Depends(get_current_user)]


# ---------- Categories ----------

@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(user: user_dependency, db: db_dependency, category: CategoryCreate):
    existing = db.query(Categories).filter(
        Categories.name == category.name,
        Categories.owner_id == user.id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A category with that name already exists"
        )
    new_category = Categories(name=category.name, owner_id=user.id)
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return new_category


@router.get("/categories", response_model=List[CategoryOut])
async def list_categories(user: user_dependency, db: db_dependency):
    return db.query(Categories).filter(Categories.owner_id == user.id).all()


# ---------- Products ----------

@router.post("/", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(user: user_dependency, db: db_dependency, product: ProductCreate):
    existing = db.query(Products).filter(
        Products.sku == product.sku,
        Products.owner_id == user.id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A product with that SKU already exists"
        )

    if product.category_id is not None:
        category = db.query(Categories).filter(
            Categories.id == product.category_id,
            Categories.owner_id == user.id
        ).first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="category_id does not exist or does not belong to you"
            )

    new_product = Products(**product.model_dump(), owner_id=user.id)
    db.add(new_product)
    db.commit()
    db.refresh(new_product)

    # Log the initial stock as a movement, if any was provided
    if new_product.stock_quantity:
        movement = StockMovements(
            product_id=new_product.id,
            quantity_change=new_product.stock_quantity,
            movement_type="initial_stock",
            note="Initial stock on product creation"
        )
        db.add(movement)
        db.commit()

    return new_product



@router.get("/", response_model=List[ProductOut])
async def list_products(
    user: user_dependency,
    db: db_dependency,
    visibility: str = Query("active", description="active, hidden, or all"),
    category_id: Optional[int] = None
):
    if visibility not in ("active", "hidden", "all"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="visibility must be one of: active, hidden, all"
        )

    query = db.query(Products).filter(Products.owner_id == user.id)
    if visibility == "active":
        query = query.filter(Products.is_active == True)
    elif visibility == "hidden":
        query = query.filter(Products.is_active == False)
    # visibility == "all": no is_active filter
    if category_id is not None:
        query = query.filter(Products.category_id == category_id)
    # Postgres returns rows in no fixed order (an updated row can move), so
    # sort by name to keep the lists in the app steady. id breaks ties.
    return query.order_by(func.lower(Products.name), Products.id).all()


@router.get("/{product_id}", response_model=ProductOut)
async def get_product(user: user_dependency, db: db_dependency, product_id: int):
    product = db.query(Products).filter(
        Products.id == product_id,
        Products.owner_id == user.id
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    user: user_dependency,
    db: db_dependency,
    product_id: int,
    product_update: ProductUpdate
):
    product = db.query(Products).filter(
        Products.id == product_id,
        Products.owner_id == user.id
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    update_data = product_update.model_dump(exclude_unset=True)
    if update_data.get("category_id") is not None:
        category = db.query(Categories).filter(
            Categories.id == update_data["category_id"],
            Categories.owner_id == user.id
        ).first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="category_id does not exist or does not belong to you"
            )

    if "sku" in update_data and update_data["sku"] != product.sku:
        existing = db.query(Products).filter(
            Products.sku == update_data["sku"],
            Products.owner_id == user.id,
            Products.id != product_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A product with that SKU already exists"
            )

    for field, value in update_data.items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product



@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_product(user: user_dependency, db: db_dependency, product_id: int):
    product = db.query(Products).filter(
        Products.id == product_id,
        Products.owner_id == user.id
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    product.is_active = False
    db.commit()
    return None


# ---------- Stock Movements ----------

@router.post(
    "/{product_id}/stock-movement",
    response_model=StockMovementOut,
    status_code=status.HTTP_201_CREATED
)
async def create_stock_movement(
    user: user_dependency,
    db: db_dependency,
    product_id: int,
    movement: StockMovementCreate
):
    # Locked so a restock and a sale happening at the same moment cannot
    # overwrite each other's stock count.
    product = db.query(Products).filter(
        Products.id == product_id,
        Products.owner_id == user.id
    ).with_for_update().first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot log stock movements for a deactivated product. Reactivate it first."
        )

    if movement.product_id != product_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="product_id in body must match product_id in URL"
        )

    new_quantity = product.stock_quantity + movement.quantity_change
    if new_quantity < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This movement would result in negative stock ({new_quantity})"
        )

    new_movement = StockMovements(**movement.model_dump())
    db.add(new_movement)

    product.stock_quantity = new_quantity

    db.commit()
    db.refresh(new_movement)
    return new_movement



@router.get("/{product_id}/stock-movements", response_model=List[StockMovementOut])
async def list_stock_movements(user: user_dependency, db: db_dependency, product_id: int):
    product = db.query(Products).filter(
        Products.id == product_id,
        Products.owner_id == user.id
    ).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
        
    return (
        db.query(StockMovements)
        .filter(StockMovements.product_id == product_id)
        .order_by(StockMovements.created_at.desc())
        .all()
    )