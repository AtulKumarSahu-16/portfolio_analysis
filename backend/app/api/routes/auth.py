from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.config import Settings, get_settings
from app.core.security import create_access_token, hash_password, require_auth_configuration, verify_password
from app.db import get_session
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])
COOKIE_NAME = "portfolio_access_token"


def set_session_cookie(response: Response, user_id: int, settings: Settings) -> None:
    token = create_access_token(user_id, settings)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/api",
    )


@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def signup(data: SignupRequest, response: Response, settings: Settings = Depends(get_settings), session: AsyncSession = Depends(get_session)):
    require_auth_configuration(settings)
    normalized_email = str(data.email).strip().lower()
    exists = await session.scalar(select(User.id).where(User.email == normalized_email))
    if exists is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=normalized_email, password_hash=hash_password(data.password), display_name=data.display_name.strip())
    if not user.display_name:
        raise HTTPException(status_code=422, detail="Display name is required.")
    session.add(user)
    try:
        await session.commit()
        await session.refresh(user)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    set_session_cookie(response, user.id, settings)
    return user


@router.post("/login", response_model=UserResponse)
async def login(data: LoginRequest, response: Response, settings: Settings = Depends(get_settings), session: AsyncSession = Depends(get_session)):
    require_auth_configuration(settings)
    normalized_email = str(data.email).strip().lower()
    user = await session.scalar(select(User).where(User.email == normalized_email))
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    set_session_cookie(response, user.id, settings)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/api", httponly=True, samesite="lax")


@router.get("/me", response_model=UserResponse)
async def current_user(user: User = Depends(get_current_user)):
    return user
