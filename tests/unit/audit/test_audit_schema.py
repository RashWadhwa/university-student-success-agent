"""Persistent audit contracts cannot represent sensitive workflow payloads."""

from backend.database.models import AuditLogModel
from backend.schemas.audit import AuditEventResponse


def test_audit_models_exclude_sensitive_payload_fields() -> None:
    forbidden = {
        "question",
        "prompt",
        "answer",
        "content",
        "evidence",
        "memory_fact",
        "chain_of_thought",
        "credential",
    }
    assert forbidden.isdisjoint(AuditLogModel.__table__.columns.keys())
    assert forbidden.isdisjoint(AuditEventResponse.model_fields)
