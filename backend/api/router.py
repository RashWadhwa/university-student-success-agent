"""Top-level and versioned API router composition."""

from fastapi import APIRouter, Depends

from backend.api.routes.ask import router as ask_router
from backend.api.routes.audit import router as audit_router
from backend.api.routes.auth import router as auth_router
from backend.api.routes.documents import router as documents_router
from backend.api.routes.evaluation import router as evaluation_router
from backend.api.routes.health import router as health_router
from backend.api.routes.llm import router as llm_router
from backend.api.routes.memory import router as memory_router
from backend.api.routes.public_config import router as public_config_router
from backend.api.routes.retrieval import router as retrieval_router
from backend.api.routes.root import router as root_router
from backend.api.routes.system import router as system_router
from backend.auth.dependencies import require_capability
from backend.auth.models import Capability
from backend.security.dependencies import rate_limit

service_router = APIRouter()
service_router.include_router(root_router)
service_router.include_router(health_router)

v1_router = APIRouter()
v1_router.include_router(auth_router)
v1_router.include_router(
    ask_router,
    dependencies=[
        Depends(require_capability(Capability.STUDENT_SUPPORT_QUERY)),
        Depends(rate_limit("ask", "rate_limit_ask")),
    ],
)
v1_router.include_router(
    llm_router,
    dependencies=[Depends(require_capability(Capability.SYSTEM_READ))],
)
v1_router.include_router(
    documents_router,
    dependencies=[
        Depends(require_capability(Capability.DOCUMENT_MANAGE)),
        Depends(rate_limit("documents", "rate_limit_documents")),
    ],
)
v1_router.include_router(
    retrieval_router,
    dependencies=[
        Depends(require_capability(Capability.PUBLIC_POLICY_READ)),
        Depends(rate_limit("retrieval", "rate_limit_retrieval")),
    ],
)
v1_router.include_router(
    evaluation_router,
    dependencies=[
        Depends(require_capability(Capability.EVALUATION_RUN)),
        Depends(rate_limit("evaluation", "rate_limit_evaluation")),
    ],
)
v1_router.include_router(
    system_router,
    dependencies=[Depends(require_capability(Capability.SYSTEM_READ))],
)
v1_router.include_router(
    memory_router,
    dependencies=[Depends(rate_limit("memory", "rate_limit_memory"))],
)
v1_router.include_router(audit_router)
v1_router.include_router(public_config_router)
