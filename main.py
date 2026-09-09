import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import auth.routes as auth_routes
import analytics.routes as analytics_routes

import drinks.session_routes as sessions_routes
import drinks.calendar_routes as calendar_routes
import drinks.sober_routes as sober_routes
import drinks.scan_routes as scan_routes

from core.config import DATABASE_URL
from core.database import init_db
import analytics.refresh_routes as refresh_routes


app = FastAPI(
    title="Limi Backend",
    description="Privacy-first alcohol awareness API",
    version="1.0.0",
)

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
app.include_router(refresh_routes.router)  # moved here
app.include_router(scan_routes.router)

@app.on_event("startup")
def startup():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    init_db()


# @app.get("/__debug/routes")
# def list_routes():
#     return [r.path for r in app.router.routes]