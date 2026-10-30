from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status
from pwdlib import PasswordHash

from app.core.config import Settings

password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"


def require_auth_configuration(settings: Settings) -> None:
    if len(settings.jwt_secret_key) < 32 or settings.jwt_secret_key.startswith("replace-with-"):
        raise HTTPException(status_code=503, detail="Authentication is not configured. Set a random JWT_SECRET_KEY of at least 32 characters.")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hash.verify(password, hashed)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, settings: Settings) -> str:
    require_auth_configuration(settings)
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=settings.access_token_expire_minutes)}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> int:
    require_auth_configuration(settings)
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.isdecimal():
            raise ValueError("Invalid subject")
        return int(subject)
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Your session is invalid or expired.") from exc
