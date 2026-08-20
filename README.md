# University Student Success Agent

Stage 5 adds a controlled, grounded question-answering workflow to the existing
FastAPI, provider, PDF-ingestion, and PostgreSQL/pgvector layers. Students can ask
about assessment problems, missed deadlines, extensions, mitigating circumstances,
reassessment, and academic appeals. Policy guidance is generated only from retrieved
university evidence and is returned with verified page-level citations.

Answers are informational. They do not approve applications, replace current
university policy, diagnose health conditions, or provide legal advice.

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

POST /api/v1/ask
        |
        v
AskService -> scope check -> RetrievalService -> evidence/freshness assessment
        |                                      -> grounded prompt
        v
LLMProvider.generate_structured -> citation/claim verification
        |                         -> deterministic confidence/escalation
        v
typed grounded response or safe fallback
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

## Stage 5 capabilities

- thin `POST /api/v1/ask` adapter over one application-scoped `AskService`
- deterministic supported-domain classification before retrieval or generation
- reuse of Stage 4 semantic, keyword, hybrid, filtering, and freshness behavior
- configurable evidence count, retrieval threshold, and context limits
- latest-effective-version selection and deterministic conflict/deadline checks
- stable `E1`, `E2`, ... evidence identifiers scoped to one request
- injection-resistant prompt construction that treats retrieved text as untrusted data
- provider-neutral structured generation through `LLMProvider.generate_structured`
- deterministic rejection of missing, duplicate, unknown, or out-of-set citations
- structural support checks for policy actions, individual approvals, and deadlines
- application-controlled high/medium/low confidence
- explicit human escalation and typed fallbacks for unsupported, insufficient,
  unverified, and temporarily unavailable outcomes
- bounded citation excerpts and safe evaluation metadata
- no durable session memory and no multi-agent orchestration

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
| `ASK_DEFAULT_TOP_K` | `5` | retrieval count when `/ask` omits `top_k` |
| `ASK_MAX_TOP_K` | `10` | maximum `/ask` retrieval count |
| `ASK_MIN_EVIDENCE_COUNT` | `1` | minimum usable passages required for generation |
| `ASK_MIN_RETRIEVAL_SCORE` | `0.5` | minimum underlying evidence score |
| `ASK_MAX_EVIDENCE_CHUNKS` | `5` | maximum passages supplied to generation |
| `ASK_EVIDENCE_MAX_CHARS_PER_CHUNK` | `2000` | per-passage prompt bound |
| `ASK_MAX_QUESTION_CHARS` | `2000` | application-level question limit |
| `CITATION_EXCERPT_MAX_CHARS` | `400` | maximum returned excerpt length |

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

## Grounded ask API

`POST /api/v1/ask` accepts a question, optional `top_k`, Stage 4 metadata filters,
and an optional non-durable `session_id`:

```json
{
  "question": "I missed an assessment because I was ill. What should I do?",
  "top_k": 5,
  "filters": {
    "document_type": "academic_policy"
  }
}
```

An answered response contains only verified citations resolved from evidence IDs:

```json
{
  "outcome": "answered",
  "answer": "The policy indicates that illness may be addressed through the mitigating circumstances procedure.",
  "recommended_actions": [
    {
      "priority": 1,
      "action": "Review the mitigating circumstances procedure.",
      "reason": "The indexed policy identifies this as the formal route."
    }
  ],
  "citations": [
    {
      "citation_id": "E1",
      "document_id": "6cc30a41-7586-4a8e-87bc-dc6028a6a800",
      "chunk_id": "fa6beb46-e2e5-445f-9665-137de9806471",
      "document_title": "Mitigating Circumstances Policy",
      "section": "4.2 Evidence",
      "page": 7,
      "source": "https://example.edu/policies/mitigating-circumstances",
      "excerpt": "Students affected by illness may submit a mitigating circumstances claim...",
      "version": "3.0",
      "effective_date": "2025-09-01",
      "retrieval_sources": ["semantic", "keyword"]
    }
  ],
  "confidence": "high",
  "limitations": [],
  "requires_human_support": false,
  "human_support_reason": null,
  "request_id": "request-123",
  "evaluation": {
    "retrieved_count": 5,
    "evidence_count": 2,
    "retrieval_strength": 0.91,
    "citation_count": 1,
    "citation_verification_passed": true
  }
}
```

The model sees short evidence IDs, not writable citation metadata. The application
maps IDs back to retrieved chunks and rejects missing, duplicate, unknown, or
out-of-set IDs. Every generated policy answer needs a citation, and every action
marked policy-based needs its own evidence IDs. Approval statements and deadline
values absent from cited text fail verification. Failed verification never returns
the unverified generated answer.

Confidence is application-controlled:

- **high**: verified citations, at least two usable passages, strong retrieval
  (`max(0.75, ASK_MIN_RETRIEVAL_SCORE + 0.2)`), and semantic+keyword agreement,
  with no older-version omission;
- **medium**: sufficient threshold-passing evidence with verified citations but not
  all high-confidence signals;
- **low**: no/weak/conflicting evidence, verification/provider failure, unsupported
  scope, or a request requiring an individual university decision.

Human support is required when evidence is absent, weak, future-only, conflicting,
or missing a requested deadline; when citations fail verification; when a provider
is unavailable; when the question is outside the supported domain; or when the
student asks whether an individual extension, claim, or appeal will be approved.
The service recommends contact but never claims to contact staff automatically.

Safe fallback outcomes distinguish `unsupported`, `insufficient_evidence`,
`verification_failed`, and `temporarily_unavailable`. These are typed responses;
ordinary request validation and unavailable initialization dependencies continue to
use the existing structured error envelope.

### Stage 5 security boundaries

- Questions, `session_id`, prompts, evidence text, generated answers, embeddings,
  credentials, and full documents are never written to application logs. Ask events
  record counts, lengths, decisions, timings, and safe provider/model identifiers.
- Both the student question and retrieved passages are explicitly marked as untrusted
  data. Document instructions cannot replace system rules, and prompt/instruction
  leakage or approval claims fail deterministic verification.
- `StrictModel` rejects extra request fields. Questions, session IDs, `top_k`, filter
  strings, evidence count, per-passage prompt content, model fields, actions,
  limitations, citations, and response excerpts are bounded.
- AskService accepts only the typed Stage 4 `SearchFilters`; users cannot provide SQL,
  operators, column names, vector expressions, or arbitrary filter fragments.
- Only the latest selected evidence up to `ASK_MAX_EVIDENCE_CHUNKS` is sent to the
  provider, with each passage separately bounded by
  `ASK_EVIDENCE_MAX_CHARS_PER_CHUNK`. OpenAI requests retain `store=False`.
- Citation sources are returned only for credential-free HTTP(S) URLs; fragments and
  credential-bearing or non-public source strings are omitted.
- Expected retrieval/provider/verification failures return safe typed fallbacks.
  Existing exception middleware suppresses stack traces and provider/database
  internals from unexpected API errors. Unexpected-error logs retain only the safe
  exception type and request context, not exception messages or tracebacks.
- `session_id` is accepted only for forward compatibility and immediately discarded.
  Stage 5 creates no conversation, question, answer, or student-profile persistence.
  Existing document/index persistence remains unchanged.

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

## Current limitations and Stage 6

- image-only PDFs still require a future OCR pipeline;
- exact vector search is intended for the initial corpus, not millions of chunks;
- freshness is metadata filtering/tie-breaking, not automatic policy supersession;
- scope classification and claim checks are deterministic rather than a full semantic
  policy classifier or sentence-level NLI system;
- `session_id` is accepted for forward compatibility but no durable memory is stored;
- no application or appeal is submitted, approved, or automatically escalated;
- the workflow does not diagnose conditions or provide legal advice.

Stage 6 can preserve this `AskService` as the measurable single-workflow baseline
while introducing coordinator, policy, support, and verifier roles behind a separate
orchestration boundary. Both approaches can share the same retrieval evidence,
citation verifier, response contract, confidence signals, and evaluation hooks, so
latency, correctness, grounding, citation quality, and escalation behavior can be
compared directly.
