"""Safe authenticated identity and session-lifecycle request/response contracts."""

from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from backend.auth.models import Capability, Role
from backend.schemas.common import StrictModel

_PASSWORD_MIN_LENGTH = 12
_PASSWORD_MAX_LENGTH = 128


def _validate_password_strength(value: str) -> str:
    if not any(character.isalpha() for character in value) or not any(
        character.isdigit() for character in value
    ):
        raise ValueError("Password must contain at least one letter and one number.")
    return value


class CurrentUserResponse(StrictModel):
    role: Role
    tenant_id: str
    capabilities: list[Capability]


class RegisterRequest(StrictModel):
    """Registration input. Deliberately has no role field: every account is student."""

    display_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)
    confirm_password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)

    @field_validator("display_name")
    @classmethod
    def normalise_display_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("display_name must not be blank")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def passwords_must_match(self) -> "RegisterRequest":
        if self.password != self.confirm_password:
            raise ValueError("password and confirm_password must match")
        return self


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=_PASSWORD_MAX_LENGTH)


class DemoLoginRequest(StrictModel):
    """Selects a pre-provisioned demo identity; never carries a password."""

    demo_role: Literal["student", "staff", "admin"]


class RefreshRequest(StrictModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class ForgotPasswordRequest(StrictModel):
    email: EmailStr


class ResetPasswordRequest(StrictModel):
    """``token_hash`` comes from the emailed recovery link's query string."""

    token_hash: str = Field(min_length=1, max_length=4096)
    new_password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)
    confirm_password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def passwords_must_match(self) -> "ResetPasswordRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("new_password and confirm_password must match")
        return self


class AuthenticatedUser(StrictModel):
    id: str
    email: str | None = None
    display_name: str | None = None
    role: Role


class AuthSession(StrictModel):
    access_token: str
    refresh_token: str
    expires_at: datetime


class AuthResponse(StrictModel):
    authenticated: bool = True
    user: AuthenticatedUser
    session: AuthSession


class RegistrationResponse(StrictModel):
    status: Literal["registered", "pending_verification"]
    message: str
    user: AuthenticatedUser | None = None
    session: AuthSession | None = None


class MessageResponse(StrictModel):
    message: str
