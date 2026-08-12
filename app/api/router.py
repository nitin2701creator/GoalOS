from fastapi import APIRouter

from app.api.v1 import agents as agents_router
from app.api.v1 import ai as ai_router
from app.api.v1 import capabilities as capabilities_router
from app.api.v1 import development as development_router
from app.api.v1 import executions as executions_router
from app.api.v1 import goals as goals_router
from app.api.v1 import integrations as integrations_router
from app.api.v1 import objectives as objectives_router
from app.api.v1 import planning as planning_router
from app.api.v1 import projects as projects_router
from app.api.v1 import schedules as schedules_router
from app.api.v1 import tasks as tasks_router
from app.api.v1 import webhooks as webhooks_router
from app.api.v1 import workflows as workflows_router

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
api_router.include_router(workflows_router.router, prefix="/v1/workflows", tags=["workflows"])
api_router.include_router(schedules_router.router, prefix="/v1/schedules", tags=["schedules"])
api_router.include_router(planning_router.router, prefix="/v1/planning", tags=["planning"])
api_router.include_router(development_router.router, prefix="/v1/development", tags=["development"])
api_router.include_router(ai_router.router, prefix="/v1/ai", tags=["ai"])
api_router.include_router(agents_router.router, prefix="/v1/agents", tags=["agents"])
api_router.include_router(capabilities_router.router, prefix="/v1/capabilities", tags=["capabilities"])
api_router.include_router(integrations_router.router, prefix="/v1/integrations", tags=["integrations"])
api_router.include_router(webhooks_router.router, prefix="/v1", tags=["webhooks"])
