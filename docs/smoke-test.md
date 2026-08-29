# Non-destructive post-deploy smoke test

Use synthetic users and public policy content only. Do not run delete-all or restore
operations against production.

1. `GET /health` returns 200 without checking external dependencies.
2. `GET /ready` returns 200 once PostgreSQL, pgvector, configuration, ingestion, and the
   primary provider are ready.
3. Streamlit loads on the login screen (not the app) and shows the configured
   institution; there is no bearer-token input anywhere.
4. Register (or sign in with) a synthetic student account through the UI — never call
   Supabase directly. Confirm the authenticated sidebar shows the correct name and role,
   and that the assigned role is `student` regardless of anything entered at signup.
5. As that student, confirm Knowledge Base, Evaluation Centre, and System Health are
   absent from the sidebar; sign out and confirm the login screen returns.
6. Sign in as a staff/admin identity and confirm those pages now appear. Directly call
   an admin-only API route (e.g. `GET /api/v1/evaluations/datasets`) with a student's
   token and confirm `403`, not just that the UI hides the page.
7. A synthetic authenticated student runs one baseline ask and sees citations.
5. The same student runs one agentic ask and sees a bounded terminal state.
6. A staff test identity uploads and indexes one approved public PDF.
7. A request correlation appears in Langfuse with safe metadata only.
8. An admin explicitly runs one bounded mock/non-sensitive evaluation case; enable the
   Gemini judge only as a separately approved paid-provider check.
9. A synthetic student consents to one harmless preference, reads it, then deletes it.
10. In staging/test, run `pytest tests/integration/test_stage8_rls.py -q` to confirm
    cross-user and cross-tenant isolation. Do not probe other production users.

Capture only status, request IDs, terminal states, and safe failure categories in the
deployment record—never tokens, questions, evidence, memory facts, or connection URLs.
