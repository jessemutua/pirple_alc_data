from fastapi import APIRouter, HTTPException

from auth.models import User
from auth.schemas import AuthPayload, AuthResponse
from core.database import SessionLocal
from core.security import hash_password, verify_password, create_token

router = APIRouter(prefix="/auth", tags=["auth"])

def serialize_user(user: User):
    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
    }


@router.post("/register", response_model=AuthResponse)
def register(payload: AuthPayload):
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == payload.email).first():
            raise HTTPException(400, "Email already exists")

        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        return {
            "access_token": create_token(user.id),
            "token_type": "bearer",
            "user": serialize_user(user),
        }
    finally:
        db.close()


@router.post("/login", response_model=AuthResponse)
def login(payload: AuthPayload):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == payload.email).first()
        if not user or not verify_password(payload.password, user.password_hash):
            raise HTTPException(401, "Invalid credentials")

        return {
            "access_token": create_token(user.id),
            "token_type": "bearer",
            "user": serialize_user(user),
        }
    finally:
        db.close()
