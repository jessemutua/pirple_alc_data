# core/security.py

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext

from .config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS


# ============================
# Security Setup
# ============================
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
security = HTTPBearer()


# ============================
# Password Hashing
# ============================
def hash_password(password: str) -> str:
    password = password.strip()
    if not password:
        raise HTTPException(status_code=400, detail="Password cannot be empty")
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password.strip(), hashed)


# ============================
# JWT Token Generation
# ============================
def create_token(user_id: str) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


# ============================
# Get Current User ID from Token
# ============================
def get_current_user_id(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    try:
        payload = jwt.decode(
            creds.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        return payload["sub"]
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
