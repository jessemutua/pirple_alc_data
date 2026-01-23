import os
from fastapi import FastAPI
from core.config import DATABASE_URL
from fastapi.middleware.cors import CORSMiddleware
from core.database import engine, Base

# ✅ Force module loading
import auth.routes as auth_routes
import drinks.routes as drinks_routes
import analytics.routes as analytics_routes

print("✅ MAIN LOADED")

# Initialize the app
app = FastAPI(
    title="Pirple Backend MVP",
    description="Privacy-first alcohol awareness API",
    version="1.0.0",
)

# CORS middleware
origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Register routers
app.include_router(auth_routes.router)
app.include_router(drinks_routes.router)
app.include_router(analytics_routes.router)

# Start the app
@app.on_event("startup")
def startup():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")

    print(f"Connecting to database at {DATABASE_URL}")
    Base.metadata.create_all(bind=engine)


@app.get("/__debug/routes")
def list_routes():
    return [r.path for r in app.router.routes]
