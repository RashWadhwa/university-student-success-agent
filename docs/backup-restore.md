# Backup and restore runbook

This application uses Supabase as managed PostgreSQL/pgvector. Enable the backup and
point-in-time recovery options appropriate to the selected Supabase plan and confirm
their retention in the Supabase dashboard. Application retention (memory and audit
expiry) is separate from provider backup retention.

For an operator-controlled logical backup, use a credential from the secret manager,
not a committed command or shell history. Prefer PostgreSQL custom format:

```text
pg_dump --format=custom --no-owner --no-acl --dbname=<source DATABASE_URL> --file=<encrypted backup path>
```

Store backups encrypted with restricted operator access and a documented destruction
date. Never copy production data into developer laptops. A staging restore must use a
new empty database and an approved, access-controlled environment:

```text
pg_restore --clean --if-exists --no-owner --no-acl --dbname=<staging DATABASE_URL> <backup file>
alembic upgrade head
```

After restore:

1. Confirm `SELECT extversion FROM pg_extension WHERE extname='vector';` succeeds.
2. Run `alembic current` and confirm `20260821_0003 (head)`.
3. Confirm private tables have both RLS and forced RLS enabled in `pg_class`.
4. Run the integration RLS suite against the staging/test database—not production.
5. Check document/chunk counts and a bounded retrieval query.
6. Record the restore exercise without credentials, row content, or private facts.

Do not automate destructive restore operations in application code. Production restore
requires an approved change window, a verified target name, current backups, rollback
ownership, and provider-specific recovery review.

The application lazily purges expired rows within the caller's RLS scope. Operations
must also schedule an owner-controlled maintenance statement for inactive accounts:
`DELETE FROM semantic_memory WHERE expires_at <= now()` and the equivalent audit/rate
counter statements. Run it through an approved database job, record row counts only,
and test it in staging first; it is intentionally not embedded in API startup.
