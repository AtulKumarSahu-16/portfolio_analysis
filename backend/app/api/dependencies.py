from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import decode_access_token
from app.db import get_session
from app.models import User


async def get_current_user(
    portfolio_access_token: str | None = Cookie(default=None),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not portfolio_access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in to continue.")
    user_id = decode_access_token(portfolio_access_token, settings)
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is unavailable.")
    return user
