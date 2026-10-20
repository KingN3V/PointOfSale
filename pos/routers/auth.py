from datetime import datetime, timedelta
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Users, PasswordResets
from ..schemas import Token, PasswordResetRequest, PasswordResetConfirm
from ..auth import hash_password, authenticate_user, create_access_token
from ..email_service import send_password_reset_email
from ..limiter import limiter


router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

logger = logging.getLogger(__name__)

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
        code = "".join(secrets.choice(RESET_CODE_ALPHABET) for _ in range(RESET_CODE_LENGTH))
        exists = db.query(PasswordResets).filter(PasswordResets.reset_token == code).first()
        if not exists:
            return code
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique reset code. Please try again."
    )


@router.post("/token", response_model=Token)
@limiter.limit("10/minute")
async def login_for_access_token(
    request: Request,
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


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def forgot_password(request: Request, db: db_dependency, body: PasswordResetRequest):
    generic_response = {
        "message": "If that email is registered, a reset code has been sent."
    }

    user = db.query(Users).filter(Users.email == body.email).first()
    if not user:
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

    # Don't reveal send failures to the client: a different response for a
    # registered email would leak which emails exist. Check the server logs.
    try:
        send_password_reset_email(user.email, code)
    except Exception:
        logger.exception("Password reset email failed to send")

    return generic_response


@router.post("/reset-password", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def reset_password(request: Request, db: db_dependency, body: PasswordResetConfirm):
    reset = db.query(PasswordResets).filter(
        PasswordResets.reset_token == body.reset_token,
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

    user.hashed_password = hash_password(body.new_password)
    reset.used = True
    db.commit()

    return {"message": "Password has been reset. You can now log in with your new password."}