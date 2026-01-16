import os
import uuid
from datetime import datetime, timedelta
from typing import Literal, Optional, Union

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, validator
from jose import jwt, JWTError
from passlib.context import CryptContext

from cors import add_cors_middleware

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    DateTime,
    Boolean,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import EmailStr, constr

# ======================
# APP
# ======================
app = FastAPI(
    title="Pirple Backend MVP",
    description="Privacy-first event ingestion API",
    version="0.3.0",
)

add_cors_middleware(app)

# ======================
# SECURITY
# ======================
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
security = HTTPBearer()

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# ======================
# DB
# ======================
engine = None
SessionLocal = None
Base = declarative_base()

# ======================
# MODELS
# ======================
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class EventLog(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    event_data = Column(JSONB, nullable=False)


class DrinkLog(Base):
    __tablename__ = "drink_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False)
    date = Column(String, nullable=False)
    drank = Column(Boolean, nullable=False)
    drink_count = Column(Integer)
    drinks = Column(JSONB)
    time_windows = Column(JSONB)
    notes = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

# ======================
# STARTUP
# ======================
@app.on_event("startup")
def startup():
    global engine, SessionLocal

    API_SECRET = os.getenv("API_SECRET")
    DATABASE_URL = os.getenv("DATABASE_URL")

    if not API_SECRET:
        raise RuntimeError("API_SECRET is not set")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://", "postgresql+psycopg2://", 1
        )

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    SessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

# ======================
# HELPERS
# ======================
def hash_password(password: str) -> str:
    if not isinstance(password, str):
        raise HTTPException(400, "Invalid password type")

    password = password.strip()

    if not password:
        raise HTTPException(400, "Password cannot be empty")

    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password.strip(), hashed)

def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


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
        raise HTTPException(status_code=401, detail="Invalid token")


def serialize_user(user: User):
    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at.isoformat(),
    }

# ======================
# SCHEMAS
# ======================
class AuthPayload(BaseModel):
    email: EmailStr
    password: constr(min_length=8, max_length=128)


class DrinkLogPayload(BaseModel):
    date: str
    drank: bool
    drink_count: Optional[int] = None
    drinks: Optional[dict[str, int]] = None
    time_windows: Optional[list[str]] = None
    notes: Optional[str] = None

# ======================
# ROUTES
# ======================
@app.get("/")
def health():
    return {"status": "ok"}

# ---------- AUTH ----------
@app.post("/auth/register")
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


@app.post("/auth/login")
def login(payload: AuthPayload):
    print("LOGIN START", payload.email)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == payload.email).first()
        print("USER FOUND", bool(user))

        if not user:
            raise HTTPException(401, "Invalid credentials")

        print("VERIFY START")
        ok = verify_password(payload.password, user.password_hash)
        print("VERIFY DONE")

        if not ok:
            raise HTTPException(401, "Invalid credentials")

        return {
            "access_token": create_token(user.id),
            "token_type": "bearer",
            "user": serialize_user(user),
        }
    finally:
        db.close()



@app.get("/auth/me")
def me(user_id: str = Depends(get_current_user_id)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(404, "User not found")

        return serialize_user(user)
    finally:
        db.close()

# ---------- EVENTS (API SECRET) ----------
@app.post("/events")
async def ingest_event(
    event: dict,
    x_api_secret: Optional[str] = Header(None, alias="X-API-Secret"),
):
    if x_api_secret != os.getenv("API_SECRET"):
        raise HTTPException(status_code=401, detail="Invalid API secret")

    db = SessionLocal()
    try:
        db_event = EventLog(event_data=event)
        db.add(db_event)
        db.commit()
        return {"status": "accepted"}
    finally:
        db.close()

# ---------- DRINK LOGS (JWT) ----------
@app.post("/drink-logs")
def ingest_drink_log(
    payload: DrinkLogPayload,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        log = DrinkLog(user_id=user_id, **payload.dict())
        db.add(log)
        db.commit()
        db.refresh(log)
        return {"log_id": log.id}
    finally:
        db.close()
from sqlalchemy import and_

@app.get("/drink-logs/month")
def get_month_logs(
    month: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    month format: YYYY-MM
    """
    db = SessionLocal()
    try:
        start = datetime.strptime(month + "-01", "%Y-%m-%d")
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)

        logs = (
            db.query(DrinkLog)
            .filter(DrinkLog.user_id == user_id)
            .filter(and_(
                DrinkLog.created_at >= start,
                DrinkLog.created_at < end,
            ))
            .all()
        )

        result = {}
        for log in logs:
            result[log.date] = {
                "drank": log.drank,
                "drink_count": log.drink_count,
            }

        return result
    finally:
        db.close()
