"""Fixtures for browser E2E tests: real backend + real frontend + real Supabase.

Excluded from default `pytest` runs (see the `e2e` marker in pyproject.toml).
Run explicitly with:

    pytest -m e2e tests/e2e --no-cov

Requires SUPABASE_AUTH_URL/SUPABASE_ANON_KEY/SUPABASE_SERVICE_ROLE_KEY in .env
(same project the app already uses) and Playwright's Chromium installed via
`playwright install chromium`. Test users are created and deleted per-test via
the Supabase admin API — nothing here depends on demo accounts existing.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page
from playwright.sync_api import expect as pw_expect

from backend.auth.supabase_provider import SupabaseAuthProvider
from backend.core.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PORT = 8010
FRONTEND_PORT = 8511
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_URL = f"http://127.0.0.1:{FRONTEND_PORT}"

_TEST_PASSWORD = "E2ETestPassword2026x"


def _wait_for(url: str, *, timeout: float = 40.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=2.0)
            if response.status_code < 500:
                return
        except httpx.RequestError as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {url}") from last_error


@pytest.fixture(autouse=True)
def _generous_timeouts(page: Page) -> None:
    # Each login round-trips to the real Supabase project (observed 150-800ms)
    # on top of a Streamlit rerender; the 5s Playwright default is too tight.
    page.set_default_timeout(15_000)
    pw_expect.set_options(timeout=15_000)


@pytest.fixture(scope="session")
def backend_process() -> Iterator[str]:
    env = os.environ.copy()
    env["ENVIRONMENT"] = "testing"
    env["LLM_PROVIDER"] = "mock"
    env["EVAL_PROVIDER"] = "mock"
    env["CORS_ORIGINS"] = f'["{FRONTEND_URL}"]'
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(BACKEND_PORT),
        ],
        cwd=REPO_ROOT,
        env=env,
    )
    try:
        _wait_for(f"{BACKEND_URL}/health")
        yield BACKEND_URL
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture(scope="session")
def frontend_process(backend_process: str) -> Iterator[str]:
    env = os.environ.copy()
    env["FASTAPI_BASE_URL"] = backend_process
    env["ENABLE_DEMO_AUTH"] = "false"
    env["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "frontend/app.py",
            "--server.address=127.0.0.1",
            f"--server.port={FRONTEND_PORT}",
            "--server.headless=true",
        ],
        cwd=REPO_ROOT,
        env=env,
    )
    try:
        _wait_for(FRONTEND_URL)
        time.sleep(2.0)  # let Streamlit finish its first script render
        yield FRONTEND_URL
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _admin_provider() -> SupabaseAuthProvider:
    settings = get_settings()
    assert settings.supabase_auth_url is not None
    assert settings.supabase_anon_key is not None
    assert settings.supabase_service_role_key is not None
    return SupabaseAuthProvider(
        auth_url=settings.supabase_auth_url,
        anon_key=settings.supabase_anon_key.get_secret_value(),
        service_role_key=settings.supabase_service_role_key.get_secret_value(),
    )


async def _create_role_user(role: str) -> tuple[str, str, str]:
    provider = _admin_provider()
    try:
        email = f"e2e-{role}-{uuid.uuid4().hex[:10]}@example.com"
        user = await provider.admin_create_user(email=email, password=_TEST_PASSWORD)
        await provider.admin_set_app_metadata(
            user_id=user.user_id,
            app_metadata={"app_role": role, "tenant_id": get_settings().default_tenant_id},
        )
        return user.user_id, email, _TEST_PASSWORD
    finally:
        await provider.close()


async def _delete_user(user_id: str) -> None:
    provider = _admin_provider()
    try:
        await provider.admin_delete_user(user_id=user_id)
    finally:
        await provider.close()


def _run_async(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine on a fresh event loop in a separate thread.

    pytest-asyncio keeps an event loop current on the main test thread for
    the whole session, so a plain ``asyncio.run()`` here would conflict with
    it (and with pytest-playwright's sync API). A dedicated thread has no
    current loop, so it's the reliable way to make a one-off async call from
    an ordinary sync fixture.
    """

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


@pytest.fixture
def student_credentials(backend_process: str) -> Iterator[tuple[str, str]]:
    user_id, email, password = _run_async(_create_role_user("student"))
    try:
        yield email, password
    finally:
        _run_async(_delete_user(user_id))


@pytest.fixture
def admin_credentials(backend_process: str) -> Iterator[tuple[str, str]]:
    user_id, email, password = _run_async(_create_role_user("admin"))
    try:
        yield email, password
    finally:
        _run_async(_delete_user(user_id))
