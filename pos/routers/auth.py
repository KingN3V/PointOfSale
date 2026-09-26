from datetime import datetime, timedelta
import random
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Users, PasswordResets
from ..schemas import UserCreate, UserOut, Token, PasswordResetRequest, PasswordResetConfirm
from ..auth import hash_password, authenticate_user, create_access_token
from ..email_service import send_password_reset_email

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

db_dependency = Annotated[Session, Depends(get_db)]

RESET_CODE_LENGTH = 8
RESET_CODE_EXPIRE_MINUTES = 15
# Excludes 0/O/1/I/L so she isn't stuck guessing which letter she's
# looking at when typing the code back in on a small screen.
RESET_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _generate_reset_code(db: Session) -> str:
    """Generates a code that doesn't already exist in PasswordResets. The
    column is unique and old rows are never deleted, so a naive random
    pick could collide with a past (expired/used) code.
    """
    for _ in range(10):
        code = "".join(random.choices(RESET_CODE_ALPHABET, k=RESET_CODE_LENGTH))
        exists = db.query(PasswordResets).filter(PasswordResets.reset_token == code).first()
        if not exists:
            return code
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique reset code. Please try again."
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register_user(db: db_dependency, create_user_request: UserCreate):
    existing_user = db.query(Users).filter(
        (Users.username == create_user_request.username) |
        (Users.email == create_user_request.email)
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with that username or email already exists"
        )

    new_user = Users(
        email=create_user_request.email,
        username=create_user_request.username,
        first_name=create_user_request.first_name,
        last_name=create_user_request.last_name,
        role=create_user_request.role,
        hashed_password=hash_password(create_user_request.password),
        is_active=True,
        phone_number=create_user_request.phone_number
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: db_dependency
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )

    token = create_access_token(user.username, user.id, user.role)

    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role
    }


# ---------- Password reset ----------

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(db: db_dependency, request: PasswordResetRequest):
    generic_response = {
        "message": "If that email is registered, a reset code has been sent."
    }

    user = db.query(Users).filter(Users.email == request.email).first()
    if not user:
        # Same response whether or not the email exists, so this endpoint
        # can't be used to check who's registered.
        return generic_response

    code = _generate_reset_code(db)
    reset = PasswordResets(
        user_id=user.id,
        reset_token=code,
        expires_at=datetime.utcnow() + timedelta(minutes=RESET_CODE_EXPIRE_MINUTES),
        used=False
    )
    db.add(reset)
    db.commit()

    # If the email fails to send, surface a real error rather than the
    # generic response — a code that was never delivered but silently
    # "succeeded" would leave her stuck with no way to know why.
    try:
        send_password_reset_email(user.email, code)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not send the reset email: {e}"
        )

    return generic_response


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(db: db_dependency, request: PasswordResetConfirm):
    reset = db.query(PasswordResets).filter(
        PasswordResets.reset_token == request.reset_token,
        PasswordResets.used == False
    ).first()

    if not reset or reset.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That reset code is invalid or has expired. Request a new one."
        )

    user = db.query(Users).filter(Users.id == reset.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = hash_password(request.new_password)
    reset.used = True
    db.commit()

    return {"message": "Password has been reset. You can now log in with your new password."}