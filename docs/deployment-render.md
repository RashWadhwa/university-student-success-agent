# Render and Supabase deployment

`render.yaml` creates separate FastAPI and Streamlit web services. The API owns every
secret and uses SQLAlchemy with `DATABASE_URL` to reach Supabase PostgreSQL/pgvector.
The UI receives only FastAPI's private host/port and safe timeout/upload settings.

## One-time setup

1. Create a Supabase project, enable `vector`, and choose asymmetric Auth signing keys.
2. Configure a Custom Access Token Hook or equivalent administrator-controlled
   `app_metadata.app_role` and `app_metadata.tenant_id`. Never authorize from mutable
   `user_metadata`.
3. Create a dedicated runtime database login that can assume `student_success_app` but
   is not a superuser, table owner, or `BYPASSRLS` role. Use its TLS connection string
   for runtime `DATABASE_URL` after the owner has run migrations.
4. Create the Render Blueprint. Enter every `sync: false` value in the dashboard;
   `render.yaml` contains no credentials.
5. Set `CORS_ORIGINS` to a JSON list containing only the exact deployed Streamlit HTTPS
   origin. Set the Supabase issuer base as `SUPABASE_AUTH_URL` ending in `/auth/v1`.

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
