"""Top-level and versioned API router composition."""

from fastapi import APIRouter

from backend.api.routes.ask import router as ask_router
from backend.api.routes.documents import router as documents_router
from backend.api.routes.evaluation import router as evaluation_router
from backend.api.routes.health import router as health_router
from backend.api.routes.llm import router as llm_router
from backend.api.routes.public_config import router as public_config_router
from backend.api.routes.retrieval import router as retrieval_router
from backend.api.routes.root import router as root_router
from backend.api.routes.system import router as system_router

service_router = APIRouter()
service_router.include_router(root_router)
service_router.include_router(health_router)

v1_router = APIRouter()
v1_router.include_router(ask_router)
v1_router.include_router(llm_router)
v1_router.include_router(documents_router)
v1_router.include_router(retrieval_router)
v1_router.include_router(evaluation_router)
v1_router.include_router(system_router)
v1_router.include_router(public_config_router)
