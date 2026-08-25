"""Idempotently provision the three demo Supabase identities used by the
Streamlit demo login buttons (Student Demo / Staff Demo / Admin Demo).

Manual, explicit invocation only:

    python scripts/seed_demo_users.py

Never runs automatically at application startup. Requires DEMO_*_EMAIL/
DEMO_*_PASSWORD and SUPABASE_SERVICE_ROLE_KEY to be set in .env for whichever
roles you want provisioned; roles with no email/password configured are
skipped. Never prints passwords or tokens. Refuses to run against a
production environment as an extra safeguard beyond ENABLE_DEMO_AUTH.
"""

from __future__ import annotations

import asyncio
import sys

from backend.auth.models import Role
from backend.auth.supabase_provider import SupabaseAuthError, SupabaseAuthProvider
from backend.core.config import get_settings


async def _seed_one(
    provider: SupabaseAuthProvider, *, role: Role, email: str | None, password: str | None
) -> None:
    if not email or not password:
        print(f"[skip] {role.value}: DEMO_{role.value.upper()}_EMAIL/PASSWORD not configured")
        return

    existing = await provider.admin_find_user_by_email(email=email)
    if existing is None:
        user = await provider.admin_create_user(email=email, password=password)
        print(f"[created] {role.value}: {email}")
    else:
        user = existing
        print(f"[exists] {role.value}: {email}")

    await provider.admin_set_app_metadata(
        user_id=user.user_id,
        app_metadata={"app_role": role.value, "tenant_id": get_settings().default_tenant_id},
    )
    print(f"[role set] {role.value}: app_metadata.app_role={role.value}")


async def main() -> int:
    settings = get_settings()

    if settings.is_production:
        print("Refusing to seed demo users: ENVIRONMENT=production.")
        return 1
    if settings.supabase_auth_url is None:
        print("SUPABASE_AUTH_URL is not configured.")
        return 1
    if settings.supabase_anon_key is None or settings.supabase_service_role_key is None:
        print("SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY are both required.")
        return 1

    provider = SupabaseAuthProvider(
        auth_url=settings.supabase_auth_url,
        anon_key=settings.supabase_anon_key.get_secret_value(),
        service_role_key=settings.supabase_service_role_key.get_secret_value(),
    )
    try:
        await _seed_one(
            provider,
            role=Role.STUDENT,
            email=settings.demo_student_email,
            password=(
                settings.demo_student_password.get_secret_value()
                if settings.demo_student_password
                else None
            ),
        )
        await _seed_one(
            provider,
            role=Role.STAFF,
            email=settings.demo_staff_email,
            password=(
                settings.demo_staff_password.get_secret_value()
                if settings.demo_staff_password
                else None
            ),
        )
        await _seed_one(
            provider,
            role=Role.ADMIN,
            email=settings.demo_admin_email,
            password=(
                settings.demo_admin_password.get_secret_value()
                if settings.demo_admin_password
                else None
            ),
        )
    except SupabaseAuthError as exc:
        print(
            f"Supabase Auth rejected a request: status={exc.status_code} code={exc.provider_code}"
        )
        return 1
    finally:
        await provider.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
