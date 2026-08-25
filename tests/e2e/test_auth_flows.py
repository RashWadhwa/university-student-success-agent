"""Browser E2E auth-flow tests against the real Streamlit UI + FastAPI + Supabase.

Excluded from default test runs — see tests/e2e/conftest.py for how to run
these explicitly. Each test that needs a signed-in identity creates its own
throwaway Supabase user via the admin API and deletes it in teardown.
"""

from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _nav_option(page: Page, name: str):
    # "Student Support" etc. also render as the main-content page header once
    # selected, so nav-visibility checks must scope to the sidebar radio group
    # specifically rather than searching the whole page for the text.
    return page.get_by_test_id("stRadioGroup").get_by_text(name, exact=True)


def test_login_screen_appears_before_app_with_no_token_box(
    frontend_process: str, page: Page
) -> None:
    page.goto(frontend_process)
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    expect(page.get_by_role("heading", name="University Student Success Assistant")).to_be_visible()

    # The main authenticated app (nav radio, pages) must not be reachable.
    expect(page.get_by_text("Student Support", exact=True)).not_to_be_visible()

    # No raw bearer-token input anywhere on the unauthenticated screen.
    expect(page.get_by_label(re.compile("access token", re.IGNORECASE))).to_have_count(0)


def test_invalid_login_shows_safe_error(frontend_process: str, page: Page) -> None:
    page.goto(frontend_process)
    page.get_by_label("Email", exact=True).fill("nobody-e2e@example.com")
    page.get_by_label("Password", exact=True).fill("definitely-wrong-password-1")
    page.get_by_role("button", name="Sign in", exact=True).click()

    expect(page.get_by_text("Invalid email or password.")).to_be_visible()
    # Still on the login screen, not silently let in.
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()


def test_registration_screen_and_password_mismatch_validation(
    frontend_process: str, page: Page
) -> None:
    page.goto(frontend_process)
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("heading", name="Create your Student Success account")).to_be_visible()

    # No role selector exists anywhere on the registration form.
    expect(page.get_by_label(re.compile("role", re.IGNORECASE))).to_have_count(0)

    page.get_by_label("Full name").fill("E2E Playwright User")
    page.get_by_label("Email", exact=True).fill(f"e2e-reg-{uuid.uuid4().hex[:8]}@example.com")
    page.get_by_label("Password", exact=True).fill("MismatchPass1234")
    page.get_by_label("Confirm password", exact=True).fill("DifferentPass5678")
    page.get_by_role("button", name="Create account", exact=True).click()

    expect(page.get_by_text("Passwords do not match.")).to_be_visible()


def test_forgot_password_renders_and_returns_generic_message(
    frontend_process: str, page: Page
) -> None:
    page.goto(frontend_process)
    page.get_by_role("button", name="Forgot password?").click()
    expect(page.get_by_role("heading", name="Reset your password")).to_be_visible()

    page.get_by_label("Email", exact=True).fill(f"e2e-forgot-{uuid.uuid4().hex[:8]}@example.com")
    page.get_by_role("button", name="Send reset instructions").click()

    expect(page.get_by_text("If an account exists for that email address")).to_be_visible()


def test_valid_login_logout_and_single_sidebar_navigation(
    frontend_process: str, page: Page, student_credentials: tuple[str, str]
) -> None:
    email, password = student_credentials
    page.goto(frontend_process)
    page.get_by_label("Email", exact=True).fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()

    expect(page.get_by_text("Signed in as")).to_be_visible()
    expect(_nav_option(page, "Student Support")).to_be_visible()

    # Exactly one navigation surface: Streamlit's own auto-generated multipage
    # nav (rendered as a bare list of un-styled page-file-derived links at the
    # very top of the sidebar) must not be present alongside the custom radio.
    expect(page.get_by_text("agent activity", exact=True)).to_have_count(0)
    expect(page.get_by_text("ask support", exact=True)).to_have_count(0)

    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
    expect(page.get_by_text("Student Support", exact=True)).not_to_be_visible()


def test_student_does_not_see_staff_or_admin_pages(
    frontend_process: str, page: Page, student_credentials: tuple[str, str]
) -> None:
    email, password = student_credentials
    page.goto(frontend_process)
    page.get_by_label("Email", exact=True).fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()

    expect(page.get_by_text("Signed in as")).to_be_visible()
    expect(_nav_option(page, "Student Support")).to_be_visible()
    expect(_nav_option(page, "Knowledge Base")).not_to_be_visible()
    expect(_nav_option(page, "Evaluation Centre")).not_to_be_visible()
    expect(_nav_option(page, "System Health")).not_to_be_visible()


def test_admin_sees_all_role_gated_pages(
    frontend_process: str, page: Page, admin_credentials: tuple[str, str]
) -> None:
    email, password = admin_credentials
    page.goto(frontend_process)
    page.get_by_label("Email", exact=True).fill(email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()

    expect(page.get_by_text("Signed in as")).to_be_visible()
    expect(_nav_option(page, "Knowledge Base")).to_be_visible()
    expect(_nav_option(page, "Evaluation Centre")).to_be_visible()
    expect(_nav_option(page, "System Health")).to_be_visible()
