# core/security.py
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext

from .config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS

# Token audiences. A token minted for one side of the product must never
# authenticate against the other.
#
# Declared as a literal rather than imported from reporting.security —
# reporting imports core, so importing back would be circular.
TOKEN_TYPE_CONSUMER = "consumer"
TOKEN_TYPE_MANUFACTURER = "manufacturer"

# Password hashing context
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# FastAPI security dependency
security = HTTPBearer()


def hash_password(password: str) -> str:
    password = (password or "").strip()
    if not password:
        raise HTTPException(status_code=400, detail="Password cannot be empty")
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify((password or "").strip(), hashed)


def create_token(user_id: str) -> str:
    payload = {
        "sub": str(user_id),
        "typ": TOKEN_TYPE_CONSUMER,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user_id(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    FastAPI dependency that decodes the incoming Bearer token and returns the `sub`.
    Raises 401 on missing/invalid/expired tokens, and on tokens issued for
    any audience other than the consumer app.
    """
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Tokens minted before typed audiences existed carry no "typ" claim —
    # those stay valid so existing sessions aren't forcibly logged out.
    # Anything explicitly typed as something else is refused.
    token_type: Optional[str] = payload.get("typ")
    if token_type is not None and token_type != TOKEN_TYPE_CONSUMER:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    return sub