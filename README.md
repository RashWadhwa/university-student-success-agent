# University Student Success Agent

Stage 2 adds a provider-independent language-model layer to the production-oriented
FastAPI foundation. The application can run with a deterministic mock provider or
OpenAI without changing the service, API, or future RAG code.

## Stage 2 deliverables

- `LLMProvider` abstract interface
- asynchronous `OpenAIProvider`
- deterministic `MockLLMProvider`
- provider factory selected through environment configuration
- OpenAI Responses API text generation
- Pydantic structured outputs
- OpenAI embeddings support
- normalised token usage, latency, model, provider, and request metadata
- SDK-level retries and explicit connection/request timeouts
- application request IDs forwarded as `X-Client-Request-Id`
- safe provider exception mapping
- provider-aware readiness checks
- development-only structured-output smoke test
- unit and API tests that do not call a paid model

Stage 2 deliberately does **not** add RAG, university documents, `/ask`, agents,
database storage, or user memory. Those features will build on this provider layer.

## Architecture

```text
FastAPI service
      |
      v
LLMProvider interface
      |
      +-------------------+
      |                   |
      v                   v
OpenAIProvider       MockLLMProvider
Responses API        deterministic tests
Embeddings API       key-free development
```

Application services will depend on `LLMProvider`, not on the OpenAI SDK. A future
`AnthropicProvider` can therefore implement the same contract and run against the
same evaluation dataset.

## Project structure added in Stage 2

```text
backend/
├── api/
│   ├── dependencies.py
│   └── routes/
│       └── llm.py
├── llm/
│   ├── base.py
│   ├── errors.py
│   ├── factory.py
│   └── providers/
│       ├── mock_provider.py
│       └── openai_provider.py
└── schemas/
    └── llm.py

tests/unit/
├── llm/
│   ├── test_factory_and_mock.py
│   └── test_openai_provider.py
└── test_llm_endpoints.py
```

## Prerequisites

- Python 3.12+
- Docker Desktop, only when using Docker
- an OpenAI API key, only when testing the real OpenAI provider

## Local setup with PowerShell

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
uvicorn backend.main:app --reload
```

Open:

- service information: `http://127.0.0.1:8000/`
- Swagger: `http://127.0.0.1:8000/docs`
- liveness: `http://127.0.0.1:8000/health`
- readiness: `http://127.0.0.1:8000/ready`
- provider status: `http://127.0.0.1:8000/api/v1/llm/status`

## Start with the mock provider

The example environment uses:

```dotenv
LLM_PROVIDER="mock"
```

This keeps the full application runnable without an API key. Check its status:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/llm/status
```

Run the fixed structured-output test:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/llm/smoke-test
```

Expected output fields include:

```json
{
  "output": {
    "message": "Provider is ready.",
    "provider_ready": true
  },
  "provider": "mock",
  "model": "mock-generation-v1"
}
```

## Enable OpenAI

Edit `.env`:

```dotenv
LLM_PROVIDER="openai"
OPENAI_API_KEY="your-api-key"
OPENAI_MODEL="gpt-5-mini"
OPENAI_EMBEDDING_MODEL="text-embedding-3-small"
```

Restart Uvicorn, then check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ready
Invoke-RestMethod http://127.0.0.1:8000/api/v1/llm/status
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/llm/smoke-test
```

The smoke test uses a fixed prompt and a small output limit. It is not an arbitrary
public generation endpoint and it is automatically unavailable when
`ENVIRONMENT="production"`.

## Provider configuration

| Variable | Default | Purpose |
|---|---:|---|
| `LLM_PROVIDER` | `openai` in code | `openai` or `mock` |
| `OPENAI_API_KEY` | unset | server-side OpenAI credential |
| `OPENAI_MODEL` | `gpt-5-mini` | generation and structured-output model |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | embedding model for the future RAG index |
| `LLM_TIMEOUT_SECONDS` | `60` | overall SDK request timeout |
| `LLM_CONNECT_TIMEOUT_SECONDS` | `5` | network connection timeout |
| `LLM_MAX_RETRIES` | `2` | SDK retry count for retryable failures |
| `LLM_MAX_OUTPUT_TOKENS` | `1200` | default generation output limit |
| `ENABLE_LLM_SMOKE_TEST` | `true` | enables the non-production diagnostic call |

The code defaults to OpenAI so an unconfigured deployment fails readiness rather
than silently using a fake model. `.env.example` deliberately selects `mock` for a
safe first local run.

## Readiness behaviour

`GET /health` reports process liveness and does not depend on the model provider.

`GET /ready` now verifies:

```json
{
  "status": "ready",
  "checks": {
    "application": "ok",
    "configuration": "ok",
    "llm_provider": "ok"
  }
}
```

When `LLM_PROVIDER="openai"` has no key, the process remains alive for diagnostics,
but `/ready` returns `503` and the model smoke test returns a structured
`LLM_CONFIGURATION_ERROR`.

## Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The container receives provider configuration from `.env`. Never place a real API
key in the Dockerfile, source code, README, or Git history.

Stop the service with:

```powershell
docker compose down
```

## Quality commands

```powershell
pytest
ruff check .
ruff format --check .
```

Apply formatting and safe lint fixes with:

```powershell
ruff format .
ruff check . --fix
```

## Stage 2 completion checklist

- application code depends on `LLMProvider`
- OpenAI is isolated behind `OpenAIProvider`
- mock mode runs with no network or API key
- text generation is normalised into `TextResult`
- structured generation returns a validated Pydantic model
- embeddings preserve input order
- timeouts and retries are configured centrally
- API and provider request IDs can be correlated
- missing OpenAI configuration fails readiness safely
- smoke test is disabled in production
- tests make no paid model calls

## Next stage

Stage 3 will implement document ingestion: PDF validation, document management,
metadata, structure-aware chunking, duplicate detection, and persistent document
and chunk models ready for PostgreSQL and pgvector.
