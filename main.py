import os
import uuid
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
from statistics import mean

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
def build_analytics(logs: list[DrinkLog], days: int) -> dict:
    if not logs:
        return {
            "meta": {
                "requestedDays": days,
                "availableDays": 0,
                "from": None,
                "to": None,
            },
            "summary": {
                "daysTracked": 0,
                "drinkingDays": 0,
                "soberDays": 0,
            },
            "trend": {
                "daily": [],
                "rollingAvg": [],
                "stats": {},
            },
            "timePattern": {},
            "drinkTypes": {},
        }

    dates = sorted({log.date for log in logs})
    available_days = len(dates)

    drinking_days = sum(1 for l in logs if l.drank)
    sober_days = available_days - drinking_days

    daily = []
    rolling = []
    window = []

    for log in logs:
        count = log.drink_count or 0

        daily.append({
            "date": log.date,
            "drank": log.drank,
            "count": count,
        })

        window.append(count)
        if len(window) > 7:
            window.pop(0)

        rolling.append({
            "date": log.date,
            "value": round(mean(window), 2),
        })

    stats = {
        "avgPerDay": round(mean([d["count"] for d in daily]), 2),
        "avgPerDrinkingDay": round(
            mean([d["count"] for d in daily if d["count"] > 0]), 2
        ) if drinking_days else 0,
        "max": max(d["count"] for d in daily),
    }

    time_pattern = defaultdict(int)

    for log in logs:
        if log.drank and log.time_windows:
            for t in log.time_windows:
                key = t.lower().replace(" ", "")
                time_pattern[key] += 1

    drink_types = defaultdict(int)

    for log in logs:
        if log.drank and log.drinks:
            for k, v in log.drinks.items():
                drink_types[k.lower()] += v

    return {
        "meta": {
            "requestedDays": days,
            "availableDays": available_days,
            "from": dates[0],
            "to": dates[-1],
        },
        "summary": {
            "daysTracked": available_days,
            "drinkingDays": drinking_days,
            "soberDays": sober_days,
        },
        "trend": {
            "daily": daily,
            "rollingAvg": rolling,
            "stats": stats,
        },
        "timePattern": dict(time_pattern),
        "drinkTypes": dict(drink_types),
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

        return build_analytics(logs, days)
    finally:
        db.close()
