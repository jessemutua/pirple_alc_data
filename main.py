import os
from fastapi import FastAPI
from core.config import DATABASE_URL
from auth.routes import router as auth_router
from drinks.routes import router as drinks_router
from analytics.routes import router as analytics_router
from fastapi.middleware.cors import CORSMiddleware
from core.database import engine, SessionLocal, Base  # Assuming engine, SessionLocal, and Base are in database.py

# Initialize the app
app = FastAPI(
    title="Pirple Backend MVP",
    description="Privacy-first alcohol awareness API",
    version="1.0.0",
)

# CORS middleware
origins = [
    "*",  # Allow all domains (could be restricted to a list of trusted domains)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register the routers from each feature module
app.include_router(auth_router)
app.include_router(drinks_router)
app.include_router(analytics_router)

# Start the app
@app.on_event("startup")
def startup():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    print(f"Connecting to database at {DATABASE_URL}")
    
    # Create all tables in the database
    Base.metadata.create_all(bind=engine)
