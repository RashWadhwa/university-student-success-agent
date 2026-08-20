"""Credential-free configuration exposed to unprivileged clients."""

from backend.schemas.common import StrictModel


class PublicConfigResponse(StrictModel):
    primary_institution_name: str
