from fastapi import APIRouter

from app.api.v1 import goals as goals_router


api_router = APIRouter()


@api_router.get("/")
async def api_root():
    return {
        "message": "Welcome to GoalOS API",
        "version": "0.5.0",
        "status": "online",
    }


@api_router.get("/ping")
async def ping():
    return {"response": "pong"}


api_router.include_router(goals_router.router, prefix="/v1/goals", tags=["goals"])