from fastapi.middleware.cors import CORSMiddleware

def add_cors_middleware(app):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "https://localhost:3000"],  # Local React dev server
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )