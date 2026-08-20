# University Student Success Agent

Stage 4 adds production-oriented RAG indexing and retrieval to the existing FastAPI,
LLM-provider, and PDF-ingestion layers. University policy documents can now be
uploaded, chunked, embedded, persisted in PostgreSQL/pgvector, and retrieved as
citation-ready evidence. Final answer generation and `/ask` remain Stage 5 work.

## Architecture

```text
POST /api/v1/documents
        |
        v
DocumentManager (validation, PDF extraction, structure-aware chunks)
        |
POST /api/v1/documents/{document_id}/index
        |
        v
IndexingService -> LLMProvider.create_embeddings -> SQLAlchemy repository
                                                   |
                                                   v
                                             PostgreSQL + pgvector
                                                   ^
                                                   |
POST /api/v1/retrieval/search -> RetrievalService -+
        |                              | semantic cosine search
        |                              | PostgreSQL full-text search
        +------------------------------+ reciprocal rank fusion
```

The code uses ordinary PostgreSQL through SQLAlchemy. Local Docker PostgreSQL and
Supabase-hosted PostgreSQL use the same models, migrations, repositories, and
business services; only `DATABASE_URL` changes. There is no Supabase client,
LangChain, external vector database, or search cluster.

## Stage 4 capabilities

- async SQLAlchemy engine and transaction-scoped sessions using `asyncpg`
- durable `documents` and `chunks` models with foreign keys and citation metadata
- pgvector embeddings generated only through `LLMProvider.create_embeddings`
- configurable embedding batch size and dimensions
- atomic indexing: embeddings complete before one database transaction persists data
- checksum idempotency and race-safe database constraints
- exact pgvector cosine search with scores normalized to `[0, 1]`
- PostgreSQL English full-text search for exact policy terminology
- typed metadata filters without caller-controlled SQL
- deterministic Reciprocal Rank Fusion (RRF), deduplication, and source attribution
- explicit evidence threshold and optional freshness tie-breaking
- Recall@k, Precision@k, Hit Rate, and reciprocal-rank helper hooks
- lightweight database/extension readiness checks without generating embeddings
- PostgreSQL/pgvector Docker service and Alembic migrations
- unit tests plus separately marked real-PostgreSQL integration tests

## Why indexing is a separate step

Stage 4 uses the retryable two-step workflow:

1. `POST /api/v1/documents` validates and durably stores an ingestion record.
2. `POST /api/v1/documents/{document_id}/index` embeds and atomically indexes it.

This keeps PDF ingestion available when PostgreSQL or the embedding provider is
temporarily unavailable, avoids half-indexed documents, and lets duplicate indexing
return `already_indexed` without regenerating embeddings.

## Local setup

Requirements:

- Python 3.12+
- Docker Desktop for local PostgreSQL integration
- an OpenAI key only when `LLM_PROVIDER="openai"`; mock mode is key-free

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
docker compose up -d database
alembic upgrade head
uvicorn backend.main:app --reload
```

The local database defaults are development-only credentials defined in Compose.
Uploaded source PDFs and `.env` are excluded from Git and the Docker build context.

To run the complete container stack, including migrations:

```powershell
docker compose up --build
```

Compose waits for PostgreSQL readiness, runs `alembic upgrade head`, and starts the
API. PostgreSQL data persists in the named `student-success-postgres` volume.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `POSTGRES_PORT` | `5432` | host port published by the local Compose database |
| `DATABASE_URL` | local PostgreSQL URL | SQLAlchemy PostgreSQL connection |
| `DATABASE_POOL_SIZE` | `5` | persistent pooled connections |
| `DATABASE_MAX_OVERFLOW` | `10` | temporary connections above the pool |
| `DATABASE_POOL_TIMEOUT` | `30` | seconds to wait for a connection |
| `DATABASE_READINESS_TIMEOUT` | `3` | maximum seconds for readiness SQL |
| `EMBEDDING_BATCH_SIZE` | `32` | chunks sent per provider embedding call |
| `EMBEDDING_DIMENSIONS` | `1536` | required vector size for indexing/query embeddings |
| `DOCUMENT_STORAGE_PATH` | `data/documents` | validated Stage 3 source storage |
| `MAX_DOCUMENT_SIZE_BYTES` | `10485760` | maximum uploaded PDF size |
| `CHUNK_SIZE` | `1200` | structure-aware target chunk size |
| `CHUNK_OVERLAP` | `200` | adjacent chunk context overlap |

`text-embedding-3-small` normally uses 1536 dimensions in this project. If the
configured provider/model emits a different size, set `EMBEDDING_DIMENSIONS` to the
exact value. Both document and query vectors are rejected when their dimensions do
not match; dimensions are never inferred from a successful request.

`DATABASE_URL` is stored as a secret setting and is never logged. Plain
`postgresql://` URLs are normalized to `postgresql+asyncpg://`. A PostgreSQL
`sslmode` query parameter is translated to asyncpg's `ssl` parameter.

## Migrations

Apply all migrations against the configured database:

```powershell
alembic upgrade head
```

Inspect the current version or roll back the Stage 4 schema:

```powershell
alembic current
alembic downgrade base
```

The initial migration:

- enables `vector` with `CREATE EXTENSION IF NOT EXISTS vector`;
- creates `documents` and `chunks` with UUID keys and cascading foreign keys;
- enforces unique document checksums and per-document chunk indexes;
- indexes document type, institution, effective date, and source;
- adds a GIN full-text index over chunk content.

No HNSW or IVFFlat index is created yet. Exact cosine search gives deterministic,
high-quality results for the initial policy collection without ANN tuning or index
training. Add HNSW only after corpus size and measured latency justify it.

## Upload and index

Upload a text-based PDF:

```powershell
$form = @{ file = Get-Item "C:\policies\assessment-policy.pdf" }
$upload = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/documents `
  -Form $form
```

Index it with policy metadata:

```powershell
$body = @{
  title = "Mitigating Circumstances Policy"
  document_type = "academic_policy"
  institution = "Example University"
  effective_date = "2026-09-01"
  version = "3.0"
  source = "https://example.edu/policies/mitigating-circumstances"
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/documents/$($upload.document.id)/index" `
  -ContentType "application/json" `
  -Body $body
```

Indexing batches all chunk texts through the configured `LLMProvider`, validates
every vector, then opens one transaction for the document and all chunks. Provider
or database failures do not leave a partial document. Re-indexing identical bytes
does not request embeddings again.

## Hybrid retrieval API

`POST /api/v1/retrieval/search` accepts a non-empty query, `top_k` from 1–20,
an evidence threshold, optional freshness preference, and typed filters:

```json
{
  "query": "What evidence is required for mitigating circumstances?",
  "top_k": 5,
  "minimum_score": 0.5,
  "prefer_recent": false,
  "filters": {
    "document_type": "academic_policy",
    "institution": "Example University",
    "effective_on_or_before": "2026-09-01"
  }
}
```

Results contain chunk/document IDs, content, page, section, title, policy metadata,
normalized score, evidence score, source-specific scores, and whether semantic,
keyword, or both retrieval paths contributed.

Semantic scores normalize cosine distance with `1 - distance / 2`, clamped to
`[0, 1]`. Keyword rank is normalized with `rank / (rank + 1)`. These incomparable
scores are not summed: RRF combines their rank positions, and the final RRF score is
normalized relative to the best candidate. `minimum_score` applies to the strongest
underlying evidence score. `prefer_recent` is an explicit effective-date tie-break;
versions are never ordered lexically.

Filters support exact `document_type`, `institution`, `source`, and `version`, plus
explicit effective-date bounds. Older versions remain searchable unless filtered.

## Health and readiness

- `GET /health` is process liveness only. It never checks PostgreSQL, Supabase,
  pgvector, OpenAI, Redis, document storage, or any network dependency.
- `GET /ready` checks application/configuration initialization, the document manager,
  provider configuration, PostgreSQL connectivity, and the `vector` extension.

Readiness performs `SELECT 1` and reads `pg_extension`; it never generates an
embedding. Database or pgvector failure returns the existing structured `503` error.

## Supabase PostgreSQL

Supabase is used only as managed PostgreSQL:

1. Open the project's **Connect** panel and copy a direct or Session Pooler PostgreSQL
   connection string. Session mode on port 5432 is suitable for this long-lived API.
2. Replace its scheme with `postgresql+asyncpg://` (plain `postgresql://` is also
   accepted and normalized), URL-encode special password characters, and add an SSL
   option such as `?sslmode=require` according to the project's SSL policy.
3. Put the value in local/hosted `DATABASE_URL`; never commit it.
4. Run `alembic upgrade head` with that environment variable configured.
5. Confirm `/ready` reports both `database` and `pgvector` as `ok`.

The migration attempts to enable `vector`. If the hosted role cannot create an
extension, enable **vector** once under Database → Extensions in the Supabase
dashboard, then rerun the same migration. No application-code changes are required.
For certificate and hostname verification, configure the CA and SSL mode supported
by the deployment environment.

## Tests and quality checks

Normal tests use deterministic mock embeddings and never call OpenAI or Supabase:

```powershell
pytest -m "not integration"
ruff check .
ruff format --check .
python -m compileall backend migrations tests
docker compose config --quiet
```

Real PostgreSQL/pgvector integration tests are explicit:

```powershell
docker compose up -d database
$env:TEST_DATABASE_URL = "postgresql+asyncpg://student_success:student_success@localhost:5432/student_success_test"
pytest -m integration -q
Remove-Item Env:TEST_DATABASE_URL
```

The Docker initialization script creates `student_success_test` on a new database
volume. The integration fixture refuses database names without `test`, upgrades the
Alembic schema, verifies connectivity and the extension, and truncates only that
dedicated test database between tests. CI needs local PostgreSQL/pgvector only—never
Supabase credentials. If an older named volume predates the initialization script,
create the test database once with:

```powershell
docker compose exec database createdb -U student_success student_success_test
```

If another PostgreSQL installation already owns host port 5432, publish the Compose
database on a different host port. This changes only host access; containers continue
to connect to `database:5432`:

```powershell
$env:POSTGRES_PORT = "55432"
docker compose up -d --force-recreate database
$env:TEST_DATABASE_URL = "postgresql+asyncpg://student_success:student_success@127.0.0.1:55432/student_success_test"
$env:DATABASE_URL = $env:TEST_DATABASE_URL
alembic upgrade head
pytest -m integration -q
```

## Current limitations and Stage 5

- image-only PDFs still require a future OCR pipeline;
- exact vector search is intended for the initial corpus, not millions of chunks;
- freshness is metadata filtering/tie-breaking, not automatic policy supersession;
- retrieval returns evidence but does not answer student questions.

Stage 5 can build `/ask` directly on citation-ready retrieval results, generate
grounded answers through `LLMProvider`, verify that claims have valid page/section
citations, express uncertainty when evidence is weak, route high-risk cases to human
support, and use the metric hooks here for retrieval and end-to-end evaluations.
