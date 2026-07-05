from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.api.router import router as api_router
from app.db.session import create_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_database()
    yield


app = FastAPI(
    title="GoalOS",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/")
async def root():
    return {"application":"GoalOS","organization":"Organigram","status":"running"}

@app.get("/health")
async def health():
    return {"status":"healthy"}

@app.get("/ready")
async def ready():
    return {"status":"ready"}
