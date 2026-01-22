import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, constr, EmailStr
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


# ======================
# APP
# ======================
app = FastAPI(
    title="Pirple Backend MVP",
    description="Privacy-first alcohol awareness API",
    version="1.0.0",
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

    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://", "postgresql+psycopg2://", 1
        )

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)


# ======================
# HELPERS
# ======================
def hash_password(password: str) -> str:
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
# ANALYTICS ENGINE
# ======================
def build_analytics(logs: list[DrinkLog]) -> dict:
    days_tracked = len({log.date for log in logs})
    drinking_days = sum(1 for log in logs if log.drank)
    sober_days = sum(1 for log in logs if not log.drank)

    drink_type = {"beer": 0, "wine": 0, "spirits": 0, "other": 0}
    quantity = {
        "oneToTwo": 0,
        "threeToFour": 0,
        "fiveToSix": 0,
        "sevenPlus": 0,
    }
    time_window = {
        "afternoon": 0,
        "evening": 0,
        "night": 0,
        "lateNight": 0,
    }

    for log in logs:
        if log.drank and log.drinks:
            for k, v in log.drinks.items():
                if k in drink_type:
                    drink_type[k] += v
                else:
                    drink_type["other"] += v

        if log.drank and log.drink_count:
            c = log.drink_count
            if c <= 2:
                quantity["oneToTwo"] += 1
            elif c <= 4:
                quantity["threeToFour"] += 1
            elif c <= 6:
                quantity["fiveToSix"] += 1
            else:
                quantity["sevenPlus"] += 1

        if log.drank and log.time_windows:
            for t in log.time_windows:
                key = t.lower().replace(" ", "")
                if key in time_window:
                    time_window[key] += 1

    return {
        "summary": {
            "daysTracked": days_tracked,
            "drinkingDays": drinking_days,
            "soberDays": sober_days,
        },
        "drinkingVsSober": {
            "drinking": drinking_days,
            "sober": sober_days,
        },
        "drinkType": drink_type,
        "quantity": quantity,
        "timeWindow": time_window,
        "moodTrend": {
            "text": "Mood analytics coming soon.",
            "direction": "stable",
        },
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


@app.post("/drink-logs")
def ingest_drink_log(
    payload: DrinkLogPayload,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        existing = (
            db.query(DrinkLog)
            .filter(DrinkLog.user_id == user_id)
            .filter(DrinkLog.date == payload.date)
            .first()
        )

        if existing:
            for k, v in payload.dict().items():
                setattr(existing, k, v)
            db.commit()
            return {"log_id": existing.id}

        log = DrinkLog(user_id=user_id, **payload.dict())
        db.add(log)
        db.commit()
        db.refresh(log)

        return {"log_id": log.id}
    finally:
        db.close()


@app.get("/drink-logs/month")
def get_month_logs(
    month: str,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        start = datetime.strptime(month + "-01", "%Y-%m-%d")
        end = (start + timedelta(days=32)).replace(day=1)

        logs = (
            db.query(DrinkLog)
            .filter(DrinkLog.user_id == user_id)
            .filter(DrinkLog.date >= start.strftime("%Y-%m-%d"))
            .filter(DrinkLog.date < end.strftime("%Y-%m-%d"))
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


@app.get("/analytics")
def get_analytics(
    days: int = 30,
    user_id: str = Depends(get_current_user_id),
):
    db = SessionLocal()
    try:
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

        logs = (
            db.query(DrinkLog)
            .filter(DrinkLog.user_id == user_id)
            .filter(DrinkLog.date >= since)
            .order_by(DrinkLog.date.asc())
            .all()
        )

        return build_analytics(logs)
    finally:
        db.close()
