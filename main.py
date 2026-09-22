import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

import auth.routes as auth_routes
import analytics.routes as analytics_routes

import drinks.session_routes as sessions_routes
import drinks.calendar_routes as calendar_routes
import drinks.sober_routes as sober_routes
import drinks.scan_routes as scan_routes
import drinks.activity_routes as activity_routes

import reporting.routes as manufacturer_routes
import reporting.report_routes as manufacturer_report_routes

from core.config import DATABASE_URL
from core.database import init_db
from core.ratelimit import limiter
import analytics.refresh_routes as refresh_routes


app = FastAPI(
    title="Limi Backend",
    description="Privacy-first alcohol awareness API",
    version="1.0.0",
)

# Rate limiting is applied per endpoint, not globally: a blanket middleware
# would also throttle the dashboard, which loads six panels at once.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(sessions_routes.router)
app.include_router(calendar_routes.router)
app.include_router(analytics_routes.router)
app.include_router(sober_routes.router)
app.include_router(refresh_routes.router)
app.include_router(scan_routes.router)
app.include_router(activity_routes.router)
app.include_router(manufacturer_routes.router)
app.include_router(manufacturer_report_routes.router)


@app.on_event("startup")
def startup():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    init_db()