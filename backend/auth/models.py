"""Trusted identity and capability types."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    STUDENT = "student"
    STAFF = "staff"
    ADMIN = "admin"


class Capability(StrEnum):
    PUBLIC_POLICY_READ = "public_policy:read"
    STUDENT_SUPPORT_QUERY = "student_support:query"
    DOCUMENT_MANAGE = "documents:manage"
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    EVALUATION_RUN = "evaluation:run"
    SYSTEM_READ = "system:read"
    AUDIT_READ = "audit:read"


ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.STUDENT: frozenset(
        {
            Capability.PUBLIC_POLICY_READ,
            Capability.STUDENT_SUPPORT_QUERY,
            Capability.MEMORY_READ,
            Capability.MEMORY_WRITE,
        }
    ),
    Role.STAFF: frozenset(
        {
            Capability.PUBLIC_POLICY_READ,
            Capability.STUDENT_SUPPORT_QUERY,
            Capability.DOCUMENT_MANAGE,
            Capability.MEMORY_READ,
            Capability.MEMORY_WRITE,
            Capability.SYSTEM_READ,
            Capability.AUDIT_READ,
        }
    ),
    Role.ADMIN: frozenset(Capability),
}


@dataclass(frozen=True, slots=True)
class Principal:
    """Identity derived only from a validated authentication context."""

    user_id: UUID
    tenant_id: str
    role: Role
    token_id: str | None = None

    def can(self, capability: Capability) -> bool:
        return capability in ROLE_CAPABILITIES[self.role]
