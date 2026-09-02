# University Student Success Agent

## Project Overview

The University Student Success Agent is a production-oriented AI system that gives
students grounded guidance on assessment problems, missed deadlines, extensions,
mitigating circumstances, reassessment, and academic appeals. Policy guidance is
generated only from retrieved university evidence and returned with verified
page-level citations — the model never answers from memory alone.

The application includes a production authentication boundary backed by Supabase
Auth, capability-based authorization for student/staff/admin roles, PostgreSQL Row
Level Security, consent-based semantic memory, persistent safe audit metadata, shared
rate limits, CI security checks, and a reproducible two-service Render deployment.

The primary institution is configuration, not application logic. The current default
and example is Harper Adams University; changing `PRIMARY_INSTITUTION_NAME`, the
curated manifest, and its official host allowlist changes the corpus without rewriting
retrieval, prompts, schemas, the portal, or evaluation code.

Answers are informational. They do not approve applications, replace current
university policy, diagnose health conditions, or provide legal advice. See
[Responsible Use](#responsible-use).

## Core Architecture

```mermaid
flowchart TD
    UI["Streamlit portal"] --> API["FastAPI"]
    API --> AU["Supabase JWT + capabilities"]
    AU --> WF["Baseline / agentic workflow"]
    WF --> RAG["RAG services + authorised tools"]
    RAG --> DB["PostgreSQL + pgvector"]
    WF --> LLM["Generation provider<br/>OpenAI / Claude-ready"]
    RAG --> LLM
    API -. "safe metadata" .-> OBS["Langfuse EU"]
    WF -. "safe metadata" .-> OBS
```

Streamlit is an HTTP-only client — it never imports backend services, connects to
PostgreSQL, or receives model/database/observability credentials. FastAPI owns
validation, authentication, workflows, ingestion, retrieval, provider access, and safe
observability. The application uses PostgreSQL through SQLAlchemy; local Docker
PostgreSQL and Supabase-hosted PostgreSQL use the same models, migrations,
repositories, and services. There is no Supabase client SDK, LangChain, external
vector database, or search cluster — Supabase is used as managed Postgres and as the
Auth provider, both over standard protocols (SQL and REST/JWKS).

Route handlers stay thin; behavior lives in the ask, agent, document, RAG, auth,
evaluation, and observability services, with repositories owning persistence queries
and provider adapters kept replaceable. See [Repository Structure](#repository-structure)
for the full module layout.

## Data Architecture

- an async SQLAlchemy engine and transaction-scoped sessions using `asyncpg`
- durable `documents` and `chunks` models with foreign keys and citation metadata
- pgvector embeddings generated only through `LLMProvider.create_embeddings`
- configurable embedding batch size and dimensions
- atomic indexing: embeddings complete before one database transaction persists data
- checksum idempotency and race-safe database constraints
- a lightweight database/extension readiness check without generating embeddings
- a PostgreSQL/pgvector Docker service for local development, and Alembic migrations
  for both local and Supabase-hosted schemas

### Why indexing is a separate step

Document ingestion uses a retryable two-step workflow:

1. `POST /api/v1/documents` validates and durably stores an ingestion record.
2. `POST /api/v1/documents/{document_id}/index` embeds and atomically indexes it.

This keeps PDF ingestion available when PostgreSQL or the embedding provider is
temporarily unavailable, avoids half-indexed documents, and lets duplicate indexing
return `already_indexed` without regenerating embeddings.

### Upload and index

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

Indexing batches all chunk texts through the configured `LLMProvider`, validates every
vector, then opens one transaction for the document and all chunks. Provider or
database failures do not leave a partial document. Re-indexing identical bytes does not
request embeddings again. The curated-corpus command (see
[Configurable Institution](#configurable-institution)) performs upload and indexing
together; manual indexing may omit `institution`, since the API supplies
`PRIMARY_INSTITUTION_NAME`, though an explicit bounded institution remains supported
for multi-institution deployments.

### Migrations

Apply all migrations against the configured database:

```powershell
alembic upgrade head
```

Inspect the current version or roll back to an empty schema:

```powershell
alembic current
alembic downgrade base
```

The migration chain (see [Repository Structure](#repository-structure) for the full
file list): enables `vector` with `CREATE EXTENSION IF NOT EXISTS vector`; creates
`documents` and `chunks` with UUID keys, cascading foreign keys, unique document
checksums, per-document chunk indexes, and a GIN full-text index over chunk content;
adds source classification; adds the authentication/RLS/audit schema described in
[Authentication and Role-Based Access](#authentication-and-role-based-access) and
[Database Security and Row Level Security](#database-security-and-row-level-security);
and enables Row Level Security on the remaining infrastructure tables.

No HNSW or IVFFlat index is created. Exact cosine search gives deterministic,
high-quality results for the current corpus size without ANN tuning or index training;
add HNSW only after corpus size and measured latency justify it.

### Supabase PostgreSQL

Supabase is used as managed PostgreSQL, reached the same way as local Docker Postgres —
through `DATABASE_URL` and SQLAlchemy, never a Supabase client SDK:

1. Open the project's **Connect** panel and copy a connection string. Production uses
   the **Session Pooler** connection (IPv4-friendly, suited to a long-lived API
   service); direct connection is also supported where IPv6 is available.
2. Replace its scheme with `postgresql+asyncpg://` (plain `postgresql://` is also
   accepted and normalized), URL-encode special password characters, and add an SSL
   option such as `?sslmode=require` according to the project's SSL policy.
3. Put the value in local/hosted `DATABASE_URL`; never commit it.
4. Run `alembic upgrade head` with that environment variable configured — this also
   provisions the `vector` extension automatically via `CREATE EXTENSION IF NOT
   EXISTS vector`, so no manual dashboard step is required first.
5. Confirm `/ready` reports both `database` and `pgvector` as `ok`.

If the connecting role cannot create extensions, enable **vector** once under
Database → Extensions in the Supabase dashboard, then rerun the same migration; no
application-code changes are required. For certificate and hostname verification,
configure the CA and SSL mode supported by the deployment environment.

## Grounded University Policy Support

```mermaid
flowchart TD
    UP["Document upload"] --> VA["PDF validation"]
    VA --> CH["Structure-aware chunking"]
    CH --> EM["Provider embeddings"]
    EM --> PG["PostgreSQL + pgvector"]
    PG --> HR["Hybrid retrieval<br/>vector + full text + RRF"]
    HR --> GA["Grounded structured answer"]
    GA --> CV["Citation and claim verification"]
```

Upload validation rejects unsafe, empty, oversized, encrypted, corrupt, and image-only
PDFs. Indexing is atomic, and hybrid retrieval returns only bounded, citation-ready
evidence with preserved document and page metadata:

- exact pgvector cosine search with scores normalized to `[0, 1]`
- PostgreSQL English full-text search for exact policy terminology
- typed metadata filters without caller-controlled SQL
- deterministic Reciprocal Rank Fusion (RRF), deduplication, and source attribution
- an explicit evidence threshold and optional freshness tie-breaking
- Recall@k, Precision@k, Hit Rate, and reciprocal-rank helper hooks for evaluation

### Hybrid retrieval API

`POST /api/v1/retrieval/search` accepts a non-empty query, `top_k` from 1–20, an
evidence threshold, optional freshness preference, and typed filters:

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

Semantic scores normalize cosine distance with `1 - distance / 2`, clamped to `[0, 1]`.
Keyword rank is normalized with `rank / (rank + 1)`. These incomparable scores are not
summed: RRF combines their rank positions, and the final RRF score is normalized
relative to the best candidate. `minimum_score` applies to the strongest underlying
evidence score. `prefer_recent` is an explicit effective-date tie-break; versions are
never ordered lexically.

Filters support exact `document_type`, `institution`, `source`, `version`,
`corpus_tier`, and `authority_scope`, plus explicit effective-date bounds. Older
versions remain searchable unless filtered. When filters are omitted at the HTTP
boundary, the configured primary institution and `primary` / `institution_policy`
classification are used (see [Configurable Institution](#configurable-institution) for
what these tiers mean).

### Grounded answers and citations

The application's grounded-answer contract — shared by the baseline and agentic
endpoints — is described in [Baseline and Agentic Modes](#baseline-and-agentic-modes).
The model sees short evidence IDs, never writable citation metadata; the application
maps IDs back to retrieved chunks and rejects missing, duplicate, unknown, or
out-of-set IDs. Every generated policy answer needs a citation, and every action
marked policy-based needs its own evidence IDs. Approval statements and deadline
values absent from cited text fail verification, and failed verification never returns
the unverified generated answer.

Confidence is application-controlled, not model-reported:

- **high**: verified citations, at least two usable passages, strong retrieval
  (`max(0.75, ASK_MIN_RETRIEVAL_SCORE + 0.2)`), and semantic+keyword agreement, with no
  older-version omission;
- **medium**: sufficient threshold-passing evidence with verified citations but not all
  high-confidence signals;
- **low**: no/weak/conflicting evidence, verification/provider failure, unsupported
  scope, or a request requiring an individual university decision.

Human support is required when evidence is absent, weak, future-only, conflicting, or
missing a requested deadline; when citations fail verification; when a provider is
unavailable; when the question is outside the supported domain; or when the student
asks whether an individual extension, claim, or appeal will be approved. The service
recommends contact but never claims to contact staff automatically. Safe fallback
outcomes distinguish `unsupported`, `insufficient_evidence`, `verification_failed`, and
`temporarily_unavailable` — these are typed responses; ordinary request validation and
unavailable initialization dependencies continue to use the existing structured error
envelope.

### Request- and answer-level security

- Questions, `session_id`, prompts, evidence text, generated answers, embeddings,
  credentials, and full documents are never written to application logs. Ask events
  record counts, lengths, decisions, timings, and safe provider/model identifiers.
- Both the student question and retrieved passages are explicitly marked as untrusted
  data. Document instructions cannot replace system rules, and prompt/instruction
  leakage or approval claims fail deterministic verification.
- `StrictModel` rejects extra request fields. Questions, session IDs, `top_k`, filter
  strings, evidence count, per-passage prompt content, model fields, actions,
  limitations, citations, and response excerpts are all bounded.
- `AskService` accepts only the typed `SearchFilters` contract; users cannot provide
  SQL, operators, column names, vector expressions, or arbitrary filter fragments.
- Only the latest selected evidence up to `ASK_MAX_EVIDENCE_CHUNKS` is sent to the
  provider, with each passage separately bounded by `ASK_EVIDENCE_MAX_CHARS_PER_CHUNK`.
  OpenAI requests retain `store=False`.
- Citation sources are returned only for credential-free HTTP(S) URLs; fragments and
  credential-bearing or non-public source strings are omitted.
- Expected retrieval/provider/verification failures return safe typed fallbacks.
  Exception middleware suppresses stack traces and provider/database internals from
  unexpected API errors; unexpected-error logs retain only the safe exception type and
  request context, not exception messages or tracebacks.
- `session_id` is accepted only for forward compatibility and immediately discarded —
  no conversation, question, answer, or student-profile persistence exists at the ask
  layer. Explicit, consented semantic memory is a separate store (see
  [Database Security and Row Level Security](#database-security-and-row-level-security)).

## Configurable Institution

`data/institutions/primary-corpus.json` is a deliberately small source manifest, not a
crawler. Its first corpus uses five public PDFs selected from the configured
institution's official [Key Information](https://www.harper-adams.ac.uk/study/1014/key-information/)
catalogue:

- [Arrangements for Claiming Mitigating Circumstances](https://cdn.harper-adams.ac.uk/document/ki/key-info-page/Mitigating-Circumstances-Arrangements-for-Claiming.pdf)
- [Assessment Scheme and Regulations 2025/26](https://cdn.harper-adams.ac.uk/document/ki/key-info-page/Assessment-Regulations.pdf)
- [Assessment Arrangements](https://cdn.harper-adams.ac.uk/document/ki/key-info-page/Assessment-Arrangements.pdf)
- [Academic Appeals Policy and Procedure 2023–2026](https://www.harper-adams.ac.uk/documents/Academic-appeals-procedure.pdf)
- [Student Engagement Policy](https://cdn.harper-adams.ac.uk/document/ki/key-info-page/Student-Engagement-Policy.pdf)

These cover mitigating circumstances, extensions, late or missed assessment,
reassessment, appeals, assessment rules, and relevant support routes. The manifest
contains no private portal links, student records, or copied policy content — it
records official URLs, titles, document types, version/date notes, and policy domains;
the configured institution value is injected at load time.

Load and index the reviewed corpus after the database migration and configured
embedding provider are ready:

```powershell
python -m backend.corpus.cli
```

The loader accepts credential-free HTTPS URLs only, rejects redirects and hosts not in
`PRIMARY_INSTITUTION_SOURCE_HOSTS`, bounds each response by `MAX_DOCUMENT_SIZE_BYTES`,
and reuses the same `DocumentManager` and `IndexingService` as manual uploads —
PDF validation, SHA-256 deduplication, page-aware chunks, embedding validation, and
atomic database writes are unchanged. Runtime download metadata (timestamp, content
type, ETag/Last-Modified when supplied, catalogue URL, corpus ID, and policy domains)
is stored in document metadata. Every indexed document's `source` is its official
public URL, so generated citations resolve to the authoritative source.

### Source tiers and authority

The knowledge base keeps public guidance in two explicit, non-interchangeable tiers:

- `primary` / `institution_policy`: official public documents from the configured
  primary university (Harper Adams, by default). This is the default for retrieval
  and `/ask`.
- `secondary` / `sector_guidance`: Discover Uni or other official UK higher-education
  guidance, used only as contextual guidance. A secondary document must name its
  publisher in `institution`; it is never presented as the primary university's rule.

The tier, authority scope, publisher/institution, title, and official source URL are
stored on each document, available as typed exact-match retrieval filters, and
returned in retrieval metadata and every `/ask` citation. The grounded prompt carries
the same labels and forbids promoting sector guidance to institution policy. When
secondary evidence is used, the answer also receives an explicit limitation explaining
its contextual status. The current curated manifest is primary only; secondary sources
must use a separately reviewed source list with explicit publisher metadata.

Synthetic information is not an accepted policy-corpus tier. It is limited to
non-production student profiles, case examples, calendars, and other private-record
fixtures needed for tests or evaluation — no real student data is included or
persisted anywhere in the system.

Unspecified API institution filters default to `PRIMARY_INSTITUTION_NAME`; callers can
still provide another bounded institution value explicitly. `GET /api/v1/config/public`
exposes only the safe display name, letting Streamlit label and prefill the current
institution without receiving secrets or backend connection details.

## Authentication and Role-Based Access

Production uses `AUTH_MODE=supabase`. FastAPI verifies each access token against the
project's asymmetric JWKS and validates its signature, issuer, audience, expiry, issue
time, and subject. Authorization data comes only from trusted `app_metadata`; mutable
user metadata and request-body `user_id` values are never trusted. `student`, `staff`,
and `admin` map to explicit capabilities enforced as FastAPI dependencies. Local
identity is available only with the explicit `AUTH_MODE=local` setting and is rejected
by production configuration validation.

```mermaid
flowchart LR
    U[User] --> S[Streamlit]
    S --> A[FastAPI]
    A --> SA[Supabase Auth]
    A --> P[(PostgreSQL)]
    P --> R[RLS]
    A --> APP[Application services]
```

```text
JWT
 ↓
authenticated user
 ↓
trusted application role (app_metadata.app_role)
 ↓
FastAPI capabilities + PostgreSQL RLS
```

| Capability | Student | Staff | Admin |
|---|:---:|:---:|:---:|
| Public policy retrieval and support queries | yes | yes | yes |
| Own semantic memory | yes | yes | yes |
| Document management | no | yes | yes |
| System status and tenant audit | no | yes | yes |
| Evaluation runs | no | no | yes |

Streamlit holds only a short-lived user access/refresh token pair in its server-side
session state — never a service-role key, database credential, or model-provider
secret. The login gate, registration, forgot/reset-password, and session-expiry
handling all run through FastAPI; Streamlit never calls Supabase directly.

### Registration, session lifecycle, and password recovery

`IdentityService` (`backend/auth/identity_service.py`) adds token *issuance* — the
flows JWKS verification alone cannot provide — via `SupabaseAuthProvider`
(`backend/auth/supabase_provider.py`), a dependency-free REST client with no
`supabase`/`gotrue` SDK. Endpoints under `/api/v1/auth`:

| Endpoint | Purpose |
|---|---|
| `POST /auth/register` | Creates an account. Always assigns `app_role=student` server-side via the admin API; the request body has no role field at all, so client-supplied role escalation is structurally impossible. |
| `POST /auth/login` | Password sign-in; returns an application-owned session (never the raw provider response). |
| `POST /auth/demo-login` | `{"demo_role": "student"\|"staff"\|"admin"}` — signs in a pre-provisioned demo identity via the same real login path. The demo password is read from server-side config and never reaches the request body, the frontend, or a log line. Returns `404` unless `ENABLE_DEMO_AUTH=true`, which is itself hard-rejected by `Settings` when `ENVIRONMENT=production`. |
| `POST /auth/refresh` | Exchanges a refresh token for a new session. |
| `POST /auth/logout` | Best-effort provider-side revoke; always clears cleanly from the caller's perspective. |
| `POST /auth/forgot-password` | Always returns the same generic message regardless of whether the account exists (anti-enumeration), whether or not the underlying email send succeeded. |
| `POST /auth/reset-password` | Takes the `token_hash` from the emailed recovery link's query string (not the URL fragment — the provider's email template is configured to use a token-hash link specifically so a server-rendered Streamlit page can read it), exchanges it server-side, then updates the password. |
| `GET /auth/me` | Reflects only the validated token's role/tenant/capabilities — no user id, email, or token is echoed. |

Demo identities (`scripts/seed_demo_users.py`) are real Supabase users with real
`app_metadata` roles, provisioned idempotently via the admin API — never a
`st.session_state.role` switch. The script refuses to run when `ENVIRONMENT=production`,
never prints passwords or tokens, and is never invoked automatically at application
startup.

## Database Security and Row Level Security

```mermaid
flowchart LR
    JWT["Validated JWT"] --> PR["Principal"]
    PR --> TX["SET LOCAL role/user/tenant"]
    TX --> RLS["RLS policies"]
    RLS --> MEM["semantic_memory<br/>owner only"]
    RLS --> AUD["audit_logs<br/>staff/admin tenant read"]
```

Row Level Security is enabled on every table in the `public` schema:

| Table | RLS | Policies | Who can actually read/write |
|---|:---:|---|---|
| `semantic_memory` | on, forced | owner+tenant isolation | Owning student only, via the app's constrained role |
| `audit_logs` | on, forced | tenant-scoped read; owner-scoped insert; expiry-scoped delete | Staff/admin (tenant-scoped read), owning user (insert) |
| `documents` | on | none | Application only (see below) |
| `chunks` | on | none | Application only |
| `rate_limit_counters` | on | none | Application only |
| `alembic_version` | on | none | Application/migration only |

A dedicated `NOLOGIN`, `NOBYPASSRLS` `student_success_app` PostgreSQL role backs the
first two tables. Private services always use `private_session()`, which starts a
transaction, assumes that constrained role, and sets validated identity as
transaction-local PostgreSQL settings — memory owners cannot read, update, or delete
another user or tenant's rows, and staff/admin audit reads remain tenant-scoped. `FORCE
ROW LEVEL SECURITY` is used only here, as defense-in-depth against the app's own
connection accidentally bypassing per-row ownership if a query ever skipped
`private_session()`.

`documents`, `chunks`, `rate_limit_counters`, and `alembic_version` are protected
differently, because their threat model is different: they hold no per-user data, so
the application (which owns these tables and reads/writes them through its normal
database connection) is trusted to see all of them in full. What RLS closes here is a
Supabase-specific exposure — Supabase grants `anon`/`authenticated` broad default
privileges on every new `public` table, which would otherwise let anyone holding the
project's anon key read or modify the RAG corpus, rate-limit counters, or migration
state directly through Supabase's REST API, completely bypassing FastAPI. Enabling RLS
with no policies denies both roles by default; the matching `REVOKE ALL` (applied only
where those roles actually exist, so local/CI PostgreSQL is unaffected) removes their
raw grants as defense-in-depth. `FORCE` is deliberately not used on these four tables —
the application's own role already fully bypasses RLS as their owner, so it adds no
protection and isn't needed architecturally the way it is for `semantic_memory`/
`audit_logs`.

Public policy documents and chunks remain intentionally shared and read-only through
the constrained role where the application chooses to use it; ordinary students can
never write to the knowledge base directly — document management stays behind the
`DOCUMENT_MANAGE` capability described in
[Authentication and Role-Based Access](#authentication-and-role-based-access).

### Semantic memory, retention, and forgetting

Memory is not a transcript store. It accepts a single bounded, distilled fact only
after explicit consent and rejects dialogue-shaped content — it stores no prompts,
answers, policy documents, embeddings, or arbitrary user identifiers.

- Preferences, accessibility preferences, and institutional context default to 365
  days; case summaries and ongoing actions default to 90 days.
- Retrieval is relational and bounded by owner, type, active state, expiry, optional
  case reference, recency, and a maximum of 50 rows. Memory is not dumped into every
  model prompt — it is never automatically injected into generation.
- Supersession deactivates an earlier fact; expiry deactivates due facts. Users can
  delete one memory, all memory, or a case-scoped subset through `/api/v1/memory`.
- Case closure is represented by case-scoped deletion; temporary interaction state is
  never promoted automatically.

## Controlled Multi-Agent Workflow

```mermaid
flowchart TD
    SR["Student request"] --> CO["Coordinator<br/>plans once"]
    CO --> RE["Retrieval Specialist"]
    RE --> PA["Policy Analyst"]
    PA --> SS["Student Support Specialist"]
    SS --> VE["Verifier"]
    VE --> CP(["completed"])
    VE --> ES(["escalated"])
    VE --> FA(["failed"])
```

A deterministic coordinator delegates single-intent questions to the baseline workflow
and uses specialists only for multi-intent questions. The registry and plan are fixed
and acyclic — user input cannot construct or rename agents, and hard task, tool,
retry, and total-provider-call budgets prevent loops. The verifier runs once and can
only complete, escalate, or fail the request; it cannot restart the workflow.

The specialist roles are deliberately narrow:

| Agent | Input | Responsibility | User-facing text |
|---|---|---|---|
| Coordinator | bounded question, filters, `top_k` | scope, intent, fixed plan | no |
| Retrieval | query and typed filters | return bounded citation-ready evidence | no |
| Policy Analyst | objective and bounded evidence | cited rules, deadlines, evidence requirements, exceptions, conflicts, uncertainties | no |
| Student Support | intent label and verified structured findings | prioritised policy/practical actions | yes |
| Verifier | final typed artifacts and evidence references | fail-closed deterministic validation | no |

There is no recursive planning, dynamic agent spawning, or open-ended agent chat. The
coordinator may plan exactly once per request; while a specialist is active, nested
dispatch — including self-dispatch — is rejected. Canonically hashed agent/input and
agent/tool/input signatures prevent identical actions from being replayed, and retries
occur only inside one bounded dispatch.

### Tools and permissions

| Tool | Permission | Authorised agent | Effect |
|---|---|---|---|
| `search_knowledge_base` | `READ` | Retrieval | bounded hybrid retrieval |
| `get_document_section` | `READ` | Retrieval, Policy Analyst | request-scoped retrieved section only |
| `find_student_service` | `READ` | Student Support | static generic service guidance |
| `draft_support_email` | `PREPARE` | Student Support | creates a bounded draft; sends nothing |

Application code validates the agent, tool, exact permission, request context, call
limit, and typed arguments before running a handler. No `EXECUTE` tool exists, and an
LLM cannot grant itself capabilities — tool inputs accept no SQL, filter expression,
filesystem path, or arbitrary agent/tool name.

### Agentic security and audit boundaries

- Policy evidence and structured tool output are explicitly delimited as untrusted
  data. Instructions to change role, ignore the coordinator, invoke unauthorised
  tools, reveal prompts, approve an appeal, or exfiltrate documents are ignored by
  prompts and rejected if they enter output.
- The Policy Analyst receives only a narrow objective and bounded evidence. Student
  Support receives an intent label and verified structured findings — not the raw
  question, document bodies, filters, database state, or prompts.
- Every specialist output is validated before entering shared request state. Support
  citations must be within the analyst's verified citation set; the final verifier
  cannot be bypassed.
- Audit events contain only request ID, fixed agent/tool names, permission, decision,
  duration, success, and failure category — questions, prompts, evidence text, model
  responses, PII, secrets, credentials, and exception messages are excluded.
- No debug endpoint is exposed. API errors and safe fallbacks contain no stack traces,
  database/provider internals, raw exceptions, prompts, or chain-of-thought.
- Coordinator, retrieval, provider, timeout, schema, tool, conflict, and verification
  failures fail closed to typed escalation responses; unverified model text is never
  returned. Every request ends irreversibly in `completed`, `escalated`, or `failed`.

## Baseline and Agentic Modes

Two endpoints share the same strict, bounded request schema and the same
grounded-answer response contract described in
[Grounded University Policy Support](#grounded-university-policy-support):

```text
POST /api/v1/ask            baseline: one AskService pass, no specialists
POST /api/v1/ask/agentic     agentic: coordinator delegates single-intent questions
                              to the baseline workflow, and multi-intent questions to
                              the specialist pipeline in
                              Controlled Multi-Agent Workflow
```

Baseline request/response:

```json
{
  "question": "I missed an assessment because I was ill. What should I do?",
  "top_k": 5,
  "filters": {
    "document_type": "academic_policy"
  }
}
```

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

The agentic response adds safe workflow metadata after the same fields:

```json
{
  "workflow": {
    "workflow_mode": "agentic",
    "agents_used": ["coordinator", "retrieval", "policy_analyst", "student_support", "verifier"],
    "tool_calls": 1,
    "retrieval_count": 1,
    "citation_count": 1,
    "confidence": "medium",
    "requires_human_support": false,
    "duration_ms": 25.4,
    "provider_calls": 3,
    "verification_passed": true,
    "terminal_state": "completed"
  }
}
```

For a supported single-intent question, `/api/v1/ask/agentic` returns
`workflow_mode: "baseline_delegated"` and calls the same `AskService` as the baseline
endpoint — this avoids unnecessary specialists while keeping the endpoint choice
explicit. `POST /api/v1/ask` never invokes the multi-agent pipeline. See
[Evaluation](#evaluation) for how the two modes are compared.

## Evaluation

```mermaid
flowchart TD
    DS["Same evaluation dataset"] --> BA["Baseline workflow"]
    DS --> AG["Agentic workflow"]
    BA --> DM["Deterministic metrics"]
    AG --> DM
    BA --> GJ["Gemini 3.1 Flash Lite judge"]
    AG --> GJ
    DM --> TC["Langfuse trace correlation"]
    GJ --> TC
    TC --> CR["Comparison results"]
```

Generation and evaluation use separate replaceable contracts:

```text
Primary generation provider
    └── OpenAI

Evaluation provider
    └── GeminiEvaluationProvider
         └── default model: gemini-3.1-flash-lite
```

`EvaluationProvider` owns the judge contract independently of `LLMProvider`.
`GeminiEvaluationProvider` reads its provider, model, and secret from typed settings;
the model identifier does not appear in provider logic, so changing the judge model
requires only an `EVAL_MODEL` configuration change. Automated tests instantiate
`MockEvaluationProvider`, which returns deterministic typed scores without network
access or an API key.

> "An independent Gemini 3.1 Flash Lite judge evaluates groundedness, policy
> correctness, completeness, and escalation quality, while deterministic checks
> continue to validate citations and other rules that do not require an LLM judge."

`data/evaluation/stage7-policy-cases.jsonl` contains 36 synthetic, PII-free cases
across policy, ambiguity, security, citation, escalation, routing, and tool-use
categories. Each selected workflow runs once per case with identical questions and
indexed evidence. `EVAL_MAX_CASES_PER_RUN`, `EVAL_MAX_JUDGE_CALLS`, and
`EVAL_TIMEOUT_SECONDS` are hard budgets — there are no recursive evaluations or
automatic judge retries.

`data/evaluation/primary-institution-validation.jsonl` adds seven representative,
PII-free questions for extensions, late and missed assessment, reassessment, appeals,
support, and fail-closed decision requests, using the same typed evaluation-case
contract; select it without code changes by setting `EVALUATION_DATASET_PATH` to that
file before application startup.

Deterministic metrics remain separate from semantic judge scores: Recall@k,
Precision@k, reciprocal rank/MRR, Hit Rate, citation validity, structured-output
validity, escalation correctness, confidence calibration, agent routing, and tool
selection. The judge scores groundedness, policy correctness, completeness,
helpfulness, and escalation correctness using only the synthetic question, expected
criteria, generated answer, bounded citation excerpts/metadata, and workflow mode —
system prompts, hidden reasoning, credentials, full documents, and unrelated traces are
excluded. Partial judge failure preserves deterministic results and cannot affect
ordinary `/ask` requests. Comparison reports baseline wins and ties rather than
assuming agentic is better.

## Observability

Langfuse is optional and isolated behind `ObservabilityService`. Disabled or failed
tracing degrades to `NoOpObservability`; it never fails `/ask`, retrieval, ingestion,
or evaluation. `/health` remains a dependency-free liveness probe, and optional
Langfuse/Gemini availability is not part of `/ready`.

Set `LANGFUSE_ENABLED=true`, keep `LANGFUSE_HOST` on the EU endpoint
`https://cloud.langfuse.com`, and set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`
only in your untracked `.env`. Placeholder values are maintained only in
`.env.example`.

The adapter correlates safe Langfuse trace IDs with existing request IDs and exports
metadata-only events for request start, retrieval, agent milestones, verification,
final response, and evaluation cases. Trace input/output is never populated.

Tracing is fail-closed for content. A strict allowlist rejects questions, answers,
documents, evidence bodies, prompts, sessions, credentials, connection strings,
emails, phone-like/free-form values, student-ID-like values, and arbitrary fields
before the Langfuse SDK sees them. Only identifiers, counts, latency/call metrics,
provider/model names, confidence, outcome, and terminal state are permitted.

## Security by Design

```mermaid
flowchart TD
    BR["Browser"] --> ST["Streamlit<br/>short-lived user token only"]
    ST --> API["FastAPI<br/>JWT + validation + capabilities"]
    API --> SV["Application services"]
    SV --> PP["Public policy corpus"]
    SV --> PR["Private memory/audit<br/>RLS"]
    SV --> EX["Model providers"]
    SV --> RD["PII redaction + allowlist"]
    RD --> LF["Langfuse EU"]
```

- No database credentials, provider keys, Supabase service-role key, or Langfuse
  secrets are exposed to the browser or Streamlit container.
- Request fields cross strict Pydantic and application-validation boundaries before
  reaching services; user-controlled SQL and filter expressions are not accepted.
- PII and sensitive content are rejected before Langfuse export (see
  [Observability](#observability)).
- The public university-policy corpus remains separate from private memory/audit data,
  enforced at the database layer (see
  [Database Security and Row Level Security](#database-security-and-row-level-security)).
- Request-level and agentic security boundaries are covered where they apply: see
  [Grounded University Policy Support](#grounded-university-policy-support) for
  ask-time protections and
  [Controlled Multi-Agent Workflow](#controlled-multi-agent-workflow) for agentic
  boundaries.

Agent audit events are persisted with only request/user/tenant identifiers, event and
agent/tool names, permission, decision, success, safe failure category, and
timestamps — raw questions, prompts, evidence, answers, memory facts, credentials, and
hidden reasoning cannot be represented by the audit schema. Audit entries expire after
180 days by default.

Authenticated expensive routes use shared PostgreSQL fixed-window counters keyed by an
HMAC pseudonym of the validated user ID. Ask, document, retrieval, evaluation, memory,
and authentication buckets (login, registration, refresh, password reset) have
separate configurable limits; a safe `429` reveals no counter or identity details.
`X-Forwarded-For` is not used for identity or limit enforcement. Request bodies are
bounded, production CORS must be an explicit allowlist, and responses carry nosniff,
referrer, permissions, CSP, and production HSTS headers.

## Testing and Quality Assurance

Normal tests use deterministic mock generation, embeddings, and
`MockEvaluationProvider`; they never call OpenAI, Gemini, or Supabase:

```powershell
pytest -m "not integration"
ruff check .
ruff format --check .
python -m compileall backend migrations tests
docker compose config --quiet
```

Frontend, observability, and evaluation checks:

```powershell
pytest tests/unit/frontend tests/unit/observability tests/unit/evaluation tests/unit/test_stage7_endpoints.py -q
streamlit run frontend/app.py --server.headless=true
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
dedicated test database between tests. CI needs local PostgreSQL/pgvector only — never
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

### Browser end-to-end tests (Playwright)

`tests/e2e` covers the authentication UI against a real, temporarily-launched FastAPI
+ Streamlit pair and the project's real identity provider — the login gate, invalid
credentials, registration (including that no role field exists), forgot-password's
generic response, sign-out, single-navigation-surface regression, and student vs. admin
page visibility. Each test that needs a signed-in identity creates its own throwaway
user via the admin API and deletes it in teardown; nothing depends on demo accounts
existing. Excluded from every default `pytest` run (see the `e2e` marker) so normal
local/CI runs never launch Chromium:

```powershell
pip install -e ".[e2e]"
playwright install chromium
pytest -m e2e tests/e2e --no-cov
```

Requires `SUPABASE_AUTH_URL`/`SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY` in `.env`
(the same project the app already uses) — install and run this suite as a
development/CI step only, never bundled into the production runtime image.
`pytest-rerunfailures` is available (`--reruns 2 --reruns-delay 2`) as cheap CI
insurance against real-network timing variance against a live external identity
provider, but is not required — the suite passes deterministically without it.

### Continuous integration

`.github/workflows/ci.yml` runs three independent jobs on every push/PR: unit +
integration tests against a real Postgres/pgvector service container (ruff, format,
`compileall`, `alembic upgrade head`, both test suites, `pip-audit`, `bandit`), a
`gitleaks` secret scan across the full git history, and a container build with a
Trivy vulnerability scan (fails on high/critical, unfixed issues ignored). Browser
E2E is intentionally not part of CI by default, since it requires real Supabase
secrets.

## Deployment

```mermaid
flowchart TD
    US["User"] --> ST["Render Streamlit"]
    ST -->|"private HTTP / public HTTPS"| API["Render FastAPI"]
    API --> AUTH["Supabase Auth<br/>JWKS verification"]
    API --> DB["Supabase PostgreSQL<br/>+ pgvector"]
    API --> GP["OpenAI / Claude-ready<br/>generation provider"]
    API --> EJ["Gemini evaluation judge"]
    API -. "redacted metadata" .-> LF["Langfuse EU"]
```

All secrets stay in server-side Render/FastAPI configuration. Streamlit receives only
the FastAPI base URL and safe public configuration.

### Local development

Requirements: Python 3.12+, Docker Desktop for local PostgreSQL, and an OpenAI key
only when `LLM_PROVIDER="openai"` (mock mode is key-free).

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

Compose waits for PostgreSQL readiness, runs `alembic upgrade head`, starts FastAPI on
`http://localhost:8000`, and starts Streamlit on `http://localhost:8501`. Streamlit
receives only `FASTAPI_BASE_URL`; provider and persistence credentials remain in the
API container. PostgreSQL data persists in the named `student-success-postgres` volume.

### Production (Render + Supabase)

`render.yaml` defines two non-root Docker web services, each built from its own
Dockerfile (`Dockerfile` for FastAPI, `Dockerfile.frontend` for Streamlit) so the two
services can never share a container command by accident. FastAPI runs Alembic once
with `alembic upgrade head` in Render's pre-deploy phase, then starts Uvicorn without
reload. Streamlit receives only the private FastAPI host/port and safe UI timeouts.
Render uses `/health` for process liveness; `/ready` remains the operator-visible
database/provider readiness probe and does not control restarts.

- `GET /health` is process liveness only — it never checks PostgreSQL, Supabase,
  pgvector, OpenAI, or any network dependency.
- `GET /ready` checks application/configuration initialization, the document manager,
  provider configuration, PostgreSQL connectivity, and the `vector` extension, via
  `SELECT 1` and a `pg_extension` read — it never generates an embedding. Database or
  pgvector failure returns the existing structured `503` error.

Both services are live on Render today, running on the Free plan (each spins down
after inactivity, adding cold-start latency — upgrade to a paid plan before any real
demo or evaluation window). Runtime database access remains SQLAlchemy →
`DATABASE_URL` → Supabase PostgreSQL and pgvector via the Session Pooler connection;
Supabase management access tokens/project references are deployment tooling, not
application runtime credentials. See [Render deployment](docs/deployment-render.md),
[backup and restore](docs/backup-restore.md), and
[post-deploy smoke tests](docs/smoke-test.md) for full operational detail.

### Configuration reference

| Variable | Default | Purpose |
|---|---:|---|
| `AUTH_MODE` | `local` | `local` (dev-only bypass) or `supabase` (production); production configuration validation rejects `local` |
| `SUPABASE_AUTH_URL` | unset | Supabase project's `/auth/v1` base URL, used for JWKS verification and token issuance |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` | expected JWT audience claim |
| `SUPABASE_ANON_KEY` | unset | required for registration/login/password-reset issuance calls |
| `SUPABASE_SERVICE_ROLE_KEY` | unset | backend-only; used solely for admin-role-assignment and demo-user provisioning |
| `ENABLE_DEMO_AUTH` | `false` | enables `/auth/demo-login`; hard-rejected by `Settings` when `ENVIRONMENT=production` |
| `RATE_LIMIT_SECRET` | dev default | HMAC key for pseudonymous rate-limit identities; required outside local/test |
| `PRIMARY_INSTITUTION_NAME` | `Harper Adams University` | shared institution display, indexing, and default retrieval filter |
| `PRIMARY_INSTITUTION_CORPUS_MANIFEST` | `data/institutions/primary-corpus.json` | reviewed official-source manifest |
| `PRIMARY_INSTITUTION_SOURCE_HOSTS` | official default institution hosts | exact HTTPS download allowlist |
| `CORPUS_DOWNLOAD_TIMEOUT_SECONDS` | `30` | timeout for each curated public PDF download |
| `POSTGRES_PORT` | `5432` | host port published by the local Compose database |
| `DATABASE_URL` | local PostgreSQL URL | SQLAlchemy PostgreSQL connection (Supabase Session Pooler URL in production) |
| `DATABASE_POOL_SIZE` | `5` | persistent pooled connections |
| `DATABASE_MAX_OVERFLOW` | `10` | temporary connections above the pool |
| `DATABASE_POOL_TIMEOUT` | `30` | seconds to wait for a connection |
| `DATABASE_READINESS_TIMEOUT` | `3` | maximum seconds for readiness SQL |
| `EMBEDDING_BATCH_SIZE` | `32` | chunks sent per provider embedding call |
| `EMBEDDING_DIMENSIONS` | `1536` | required vector size for indexing/query embeddings |
| `DOCUMENT_STORAGE_PATH` | `data/documents` | validated source storage |
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
| `AGENT_MAX_TASKS` | `4` | maximum coordinator tasks |
| `AGENT_MAX_TOOL_CALLS` | `4` | maximum authorised tool calls per request |
| `AGENT_TIMEOUT_SECONDS` | `20` | timeout for each specialist attempt |
| `AGENT_MAX_RETRIES` | `1` | bounded specialist retries |
| `AGENT_MAX_EVIDENCE_ITEMS` | `5` | maximum evidence items shared with specialists |
| `AGENT_MAX_PROVIDER_CALLS` | `5` | hard total provider/model call budget per workflow |
| `EVAL_PROVIDER` | `gemini` | independent evaluation provider |
| `EVAL_MODEL` | `gemini-3.1-flash-lite` | configuration-selected LLM-as-judge model |
| `GEMINI_API_KEY` | unset | secret used only by the Gemini evaluation provider |
| `EVAL_MAX_CASES_PER_RUN` | `50` | hard maximum selected cases per evaluation |
| `EVAL_MAX_JUDGE_CALLS` | `100` | hard total semantic-judge calls per run |
| `EVAL_TIMEOUT_SECONDS` | `30` | per-workflow and per-judge timeout |
| `EVALUATION_DATASET_PATH` | `data/evaluation/stage7-policy-cases.jsonl` | fixed synthetic dataset |
| `LANGFUSE_ENABLED` | `false` | enable optional tracing |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse Cloud EU endpoint |
| `LANGFUSE_PUBLIC_KEY` | unset | Langfuse public credential, backend only |
| `LANGFUSE_SECRET_KEY` | unset | Langfuse secret credential, backend only |
| `LANGFUSE_EVENT_TIMEOUT_SECONDS` | `0.5` | hard non-blocking trace export budget |
| `FASTAPI_BASE_URL` | `http://localhost:8000` | Streamlit-to-FastAPI URL |
| `FRONTEND_MAX_UPLOAD_BYTES` | `10485760` | client-side PDF upload bound; backend revalidates |

`text-embedding-3-small` normally uses 1536 dimensions in this project. If the
configured provider/model emits a different size, set `EMBEDDING_DIMENSIONS` to the
exact value — both document and query vectors are rejected when their dimensions do
not match, and dimensions are never inferred from a successful request.

`DATABASE_URL` and every credential above are stored as secret settings and never
logged. Plain `postgresql://` URLs are normalized to `postgresql+asyncpg://`, and a
PostgreSQL `sslmode` query parameter is translated to asyncpg's `ssl` parameter.

## Responsible Use

Answers are informational. They do not approve applications, replace current
university policy, diagnose health conditions, or provide legal advice.

Known limitations:

- image-only PDFs still require a future OCR pipeline;
- exact vector search suits the current corpus size, not millions of chunks;
- freshness is metadata filtering/tie-breaking, not automatic policy supersession;
- scope classification and claim checks are deterministic rather than a full semantic
  policy classifier or sentence-level NLI system;
- `session_id` remains non-durable; only explicit, consented, distilled facts enter the
  separate semantic-memory store;
- no application or appeal is submitted, approved, or automatically escalated;
- the workflow does not diagnose conditions or provide legal advice.

Before a live launch with real students, operators must: configure the Supabase
project's Auth settings (email confirmation, a verified custom SMTP sending domain)
described in [Authentication and Role-Based Access](#authentication-and-role-based-access);
provision Render secret environment values; approve CORS origins; review data
retention with the institution's data owner; exercise a restore into staging; and
complete the documented smoke test
([docs/smoke-test.md](docs/smoke-test.md)). OCR, automated case-system integration,
and automatic memory-to-prompt injection remain intentionally out of scope.

## Repository Structure

```text
.
├── backend/                  # FastAPI application and domain services
├── frontend/                 # Unprivileged Streamlit HTTP client
├── data/
│   ├── evaluation/           # Versioned synthetic evaluation datasets
│   └── institutions/         # Reviewed public-policy source manifests
├── docs/                     # Demo and operator-facing documentation
├── scripts/                  # Offline, explicitly-invoked operator tooling
├── .github/workflows/        # CI, security and container validation
├── migrations/               # Alembic environment and versioned schema changes
├── tests/
│   ├── e2e/                  # Playwright browser tests (dev/CI only)
│   ├── integration/          # Real PostgreSQL/pgvector workflow tests
│   └── unit/                 # Isolated API and domain tests with mock providers
├── docker/postgres/init/     # Local test-database bootstrap SQL
├── .dockerignore             # Container build exclusions
├── .env.example              # Placeholders and non-secret configuration examples
├── .gitignore                # Local secrets, caches, storage, and build exclusions
├── alembic.ini                # Alembic configuration
├── docker-compose.yml         # Local API, frontend, migration, and database stack
├── Dockerfile                 # FastAPI container image
├── Dockerfile.frontend        # Streamlit container image
├── render.yaml                 # Separate Render API/UI services and release migration
├── pyproject.toml              # Package, tooling, and test configuration (authoritative)
├── requirements.txt             # `pip install .` compatibility shim only
└── README.md
```

### Backend

```text
backend/
├── api/
│   ├── dependencies.py       # FastAPI dependency accessors
│   ├── router.py             # Versioned route composition
│   └── routes/                # Versioned endpoint modules, including auth.py
├── agents/                   # Bounded coordinator, specialists, tools, verifier
├── audit/                    # Minimized persistent security audit service
├── auth/                     # Supabase JWT verification, token issuance, capabilities
│   ├── service.py            # JWKS verification (AuthenticationService)
│   ├── identity_service.py   # Register/login/refresh/logout/password-reset
│   └── supabase_provider.py  # Dependency-free Supabase Auth REST client
├── ask/                       # Baseline grounded-answer workflow and verification
├── core/                       # Typed settings, logging, middleware, errors, context
├── corpus/                     # Reviewed official-source manifest loader and CLI
├── database/                   # Async SQLAlchemy engine and ORM models
├── documents/                   # PDF validation, extraction, chunking, ingestion records
├── evaluation/                   # Provider-independent evaluation runner and metrics
├── llm/                           # Generation/embedding provider interface and adapters
├── memory/                        # Consent, retention, supersession, and deletion policy
├── observability/                  # Redaction, no-op tracing, and Langfuse adapter
├── rag/                              # Indexing, hybrid retrieval, fusion, retrieval metrics
├── repositories/                      # Persistence and search query boundary
├── schemas/                            # Strict external Pydantic request/response contracts
├── security/                            # Rate limiting and HTTP hardening
└── main.py                               # FastAPI application factory and service wiring
```

### Frontend

```text
frontend/
├── app.py                    # Streamlit entry point, auth gate, and navigation
├── api_client.py             # Sole typed HTTP boundary to FastAPI
├── config.py                 # Frontend-only safe settings
├── state.py                  # Non-durable UI/session state, incl. auth session
├── components/
│   ├── citations.py          # Bounded, source-labelled citations
│   ├── metrics.py            # Safe evaluation/workflow metrics
│   ├── status.py             # Service status presentation
│   └── workflow.py           # Agent workflow presentation
└── views/
    ├── auth.py                # Login, registration, forgot/reset-password screens
    ├── ask_support.py
    ├── knowledge_base.py
    ├── evidence_explorer.py
    ├── agent_activity.py
    ├── evaluation.py
    └── system.py
```

Named `views/`, not `pages/`, so Streamlit's automatic multipage navigation (which
activates for any folder literally named `pages` next to the entry script) never
creates a second, duplicate navigation surface alongside the custom sidebar in
`app.py`. The frontend does not import backend services, connect to PostgreSQL, or
receive model, database, evaluation, Supabase, or observability credentials — it
renders only typed API results and safe translated errors.

### Evaluation and observability

```text
backend/
├── evaluation/
│   ├── base.py               # Replaceable EvaluationProvider contract
│   ├── dataset.py            # Bounded JSONL dataset loading
│   ├── errors.py             # Safe evaluator failure categories
│   ├── factory.py            # Configuration-selected provider construction
│   ├── metrics.py            # Deterministic scoring
│   ├── models.py             # Strict evaluation contracts
│   ├── runner.py             # Baseline/agentic comparison orchestration
│   ├── tracing.py            # Safe evaluator trace metadata
│   └── providers/
│       ├── gemini_provider.py
│       └── mock_provider.py
└── observability/
    ├── base.py               # Observability interface
    ├── events.py             # Bounded event vocabulary
    ├── factory.py            # Langfuse/no-op selection
    ├── langfuse.py           # Privacy-safe Langfuse adapter
    ├── noop.py               # Failure-safe disabled implementation
    └── redaction.py          # Metadata allowlist and PII/secret rejection
data/evaluation/              # Synthetic, PII-free evaluation cases
tests/unit/evaluation/        # Judge, metrics, runner, and configuration tests
tests/unit/observability/     # Redaction and trace-boundary tests
```

### Deployment and infrastructure

```text
Dockerfile                     # FastAPI application image
Dockerfile.frontend            # Streamlit application image (separate CMD/health check)
docker-compose.yml             # Local PostgreSQL, migrations, API, and frontend
render.yaml                    # Production Blueprint: release migration + two services
.github/workflows/ci.yml       # Tests, scans, migrations, and image validation
docker/postgres/init/
└── 01-create-test-database.sql
scripts/
└── seed_demo_users.py         # Idempotent demo-account provisioning; manual invocation only
migrations/
├── env.py                     # Async migration environment
├── script.py.mako
└── versions/
    ├── 20260820_0001_stage4_rag.py
    ├── 20260820_0002_source_classification.py
    ├── 20260821_0003_stage8_security.py
    └── 20260829_0004_rls_infrastructure_tables.py
alembic.ini
.env.example                   # Placeholders only; .env remains untracked
```
