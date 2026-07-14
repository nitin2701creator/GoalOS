from fastapi import APIRouter

from app.api.v1 import goals as goals_router
from app.api.v1 import objectives as objectives_router
from app.api.v1 import projects as projects_router
from app.api.v1 import tasks as tasks_router
from app.api.v1 import executions as executions_router


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
api_router.include_router(objectives_router.router, prefix="/v1/objectives", tags=["objectives"])
api_router.include_router(projects_router.router, prefix="/v1/projects", tags=["projects"])
api_router.include_router(tasks_router.router, prefix="/v1/tasks", tags=["tasks"])
api_router.include_router(executions_router.router, prefix="/v1", tags=["executions"])
