import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import auth.routes as auth_routes
import analytics.routes as analytics_routes

# NEW routers (sessions-only)
import drinks.sessions_routes as sessions_routes
import drinks.calendar_routes as calendar_routes

from core.config import DATABASE_URL
from core.database import init_db

print("✅ MAIN LOADED")

app = FastAPI(
    title="Pirple Backend MVP",
    description="Privacy-first alcohol awareness API",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_routes.router)
app.include_router(sessions_routes.router)
app.include_router(calendar_routes.router)
app.include_router(analytics_routes.router)


@app.on_event("startup")
def startup():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    print(f"Connecting to database at {DATABASE_URL}")

    # IMPORTANT: uses init_db() which imports models first, then create_all
    init_db()


@app.get("/__debug/routes")
def list_routes():
    return [r.path for r in app.router.routes]