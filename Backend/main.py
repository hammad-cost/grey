from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.ai_strategy import router as ai_strategy_router
from app.api.fyp_design import router as fyp_design_router
from app.api.problems import router as problems_router
from app.api.project_definition import router as project_definition_router
from app.api.projects import router as projects_router
from app.api.research import router as research_router
from app.core.brain.database import create_all_tables
from app.core.config import settings
from app.core.llm import build_llm_gateway
from app.core.skills.registry import skill_registry
from app.core.tools import get_search_provider
from app.domains.fyp.skills import register_fyp_skills


def register_skills() -> None:
    """
    Put every skill into the shared skill registry, giving each one the tools
    configured in .env (SEARCH_PROVIDER, LLM_MODE, …). Safe to call more than once.
    """
    if "research_evidence" not in skill_registry:
        register_fyp_skills(
            skill_registry,
            get_search_provider(settings),
            build_llm_gateway(settings),
            max_searches=settings.research_max_searches,
            max_dataset_searches=settings.dataset_max_searches,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs once at startup, then again at shutdown.
    The code before 'yield' runs on startup; after 'yield' on shutdown.
    """
    await create_all_tables()
    register_skills()
    yield


app = FastAPI(
    title="Grey API",
    version="0.7.0",
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
app.include_router(research_router)
app.include_router(problems_router)
app.include_router(fyp_design_router)
app.include_router(project_definition_router)
app.include_router(ai_strategy_router)


@app.get("/health")
def health_check():
    """Confirms the server is running and shows the current configuration."""
    return {
        "status": "ok",
        "app_env": settings.app_env,
        "database_url": settings.database_url,
    }
