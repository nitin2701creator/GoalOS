from fastapi import FastAPI

from app.api.router import api_router
from app.db.base import Base
from app.db.session import engine


app = FastAPI(
    title="GoalOS",
    description="Enterprise AI Operating System",
    version="0.5.0",
)


app.include_router(api_router, prefix="/api")


@app.on_event("startup")
def on_startup():
    # Create DB tables if they don't exist
    Base.metadata.create_all(bind=engine)


@app.get("/")
async def root():
    return {
        "name": "GoalOS",
        "status": "running",
        "version": "0.5.0",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }