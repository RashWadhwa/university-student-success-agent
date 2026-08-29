# Render and Supabase deployment

`render.yaml` creates separate FastAPI and Streamlit web services. The API owns every
secret and uses SQLAlchemy with `DATABASE_URL` to reach Supabase PostgreSQL/pgvector.
The UI receives only FastAPI's private host/port and safe timeout/upload settings.

## One-time setup

1. Create a Supabase project and choose asymmetric Auth signing keys. `vector` does not
   need to be enabled manually — the first Stage 4 migration runs
   `CREATE EXTENSION IF NOT EXISTS vector` itself, so Render's pre-deploy
   `alembic upgrade head` provisions it automatically on first deploy.
2. `app_metadata.app_role`/`app_metadata.tenant_id` are set server-side by
   `IdentityService`/`SupabaseAuthProvider` (`backend/auth/identity_service.py`) via the
   Supabase admin API immediately after registration — not a Custom Access Token Hook.
   Every new account is assigned `app_role=student` unconditionally; there is no
   endpoint or code path that accepts a client-supplied role. Never authorize from
   mutable `user_metadata`.
3. Create a dedicated runtime database login that can assume `student_success_app` but
   is not a superuser, table owner, or `BYPASSRLS` role. Use its TLS connection string
   for runtime `DATABASE_URL` after the owner has run migrations.
4. Create the Render Blueprint. Enter every `sync: false` value in the dashboard;
   `render.yaml` contains no credentials.
5. Set `CORS_ORIGINS` to a JSON list containing only the exact deployed Streamlit HTTPS
   origin. Set the Supabase issuer base as `SUPABASE_AUTH_URL` ending in `/auth/v1`.
6. Before real users register, confirm "Confirm email" is **on** in Supabase's Email
   provider settings, and that a custom SMTP provider (not the default sandbox sender)
   is configured with a verified sending domain — the default/sandbox sender can only
   deliver to the Supabase account owner's own address.
7. Keep `ENABLE_DEMO_AUTH=false` in this production service (already the `render.yaml`
   default; `Settings` hard-rejects `true` when `ENVIRONMENT=production` regardless). If
   a demo/video-recording deployment with demo accounts is wanted, provision it as a
   **separate** Render Blueprint/environment pointed at its own Supabase project (or at
   minimum non-production `ENVIRONMENT` value) rather than enabling demo auth here.

## Environment variables by service

Backend (`student-success-api`) receives every secret; frontend receives none of them.

| Variable | Service | Notes |
|---|---|---|
| `DATABASE_URL` | API only | Supabase Postgres connection string; `sync: false` |
| `SUPABASE_AUTH_URL` | API only | `https://<ref>.supabase.co/auth/v1`; `sync: false` |
| `SUPABASE_ANON_KEY` | API only | `sync: false` |
| `SUPABASE_SERVICE_ROLE_KEY` | API only | `sync: false`; used only for admin-role-assignment calls |
| `OPENAI_API_KEY`, `GEMINI_API_KEY` | API only | `sync: false` |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | API only | `sync: false` |
| `RATE_LIMIT_SECRET` | API only | `generateValue: true` |
| `CORS_ORIGINS` | API only | `sync: false`; set once the frontend's Render URL is known |
| `ENABLE_DEMO_AUTH` | API only | `"false"` in this Blueprint |
| `FASTAPI_BASE_URL` | Frontend only | wired automatically via Render's `fromService` private hostport |
| `FRONTEND_REQUEST_TIMEOUT_SECONDS`, `FRONTEND_MAX_UPLOAD_BYTES` | Frontend only | non-secret UI tuning |

`CORS_ORIGINS` is a chicken-and-egg value: the frontend's `.onrender.com` URL isn't
known until it's deployed once. Deploy both services, then set `CORS_ORIGINS` to the
frontend's exact HTTPS origin and redeploy the API.

## Release process

Render runs this controlled pre-deploy command on the API service:

```text
alembic upgrade head
```

It runs once per deployment, outside API worker startup. The API then starts Uvicorn
without `--reload`; graceful shutdown has 30 seconds. `/health` is the Render liveness
check. `/ready` is for operational dependency visibility and can return 503 during an
external outage without causing a liveness restart.

For migration rollback, first restore/test in staging. Prefer a forward corrective
migration. If the migration's downgrade is proven safe and data-loss implications are
approved, run `alembic downgrade <prior revision>` as a controlled operator action.
Never let each worker race migrations during startup.

Supabase project references and access tokens are administrative tooling only. They are
not required by the running API. Supabase service-role keys must not be supplied to
Streamlit or used for ordinary RAG/private-table queries.
