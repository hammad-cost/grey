from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.projects import router as projects_router
from app.core.brain.database import create_all_tables
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup, then again at shutdown.
    The code before 'yield' runs on startup; after 'yield' on shutdown.
    """
    await create_all_tables()
    yield


app = FastAPI(
    title="Grey API",
    version="0.1.0",
    lifespan=lifespan,
)

# Lets the browser-based frontend (a different origin/port) call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)


@app.get("/health")
def health_check():
    """Confirms the server is running and shows the current configuration."""
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "database_url": settings.database_url,
    }
