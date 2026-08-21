"""Safe authenticated identity response."""

from backend.auth.models import Capability, Role
from backend.schemas.common import StrictModel


class CurrentUserResponse(StrictModel):
    role: Role
    tenant_id: str
    capabilities: list[Capability]
