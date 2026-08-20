# University Student Success Agent

Stage 3 adds production PDF ingestion directly to the existing Stage 1 FastAPI
foundation and Stage 2 provider-independent LLM layer. It validates, extracts,
chunks, deduplicates, and durably stores university documents without making an
OpenAI call.

## What Stage 3 provides

- `POST /api/v1/documents` multipart PDF upload
- extension, MIME type, PDF signature, and configurable size validation
- explicit rejection of empty, corrupt, encrypted, page-less, and image-only PDFs
- path-traversal rejection plus sanitised display filenames
- SHA-256 checksums and duplicate detection that survives application restarts
- PDF-level metadata and page number, dimensions, rotation, and extracted text
- structure-aware chunks that prefer heading, paragraph, sentence, and word boundaries
- configurable `CHUNK_SIZE` and `CHUNK_OVERLAP`
- checksum-named PDF storage and atomically written typed JSON sidecars
- a `DocumentManager` service that owns the ingestion workflow while API routes stay thin
- structured logging and the existing request-correlated error envelope
- unit and API tests using local generated PDFs and the deterministic mock LLM provider

All Stage 1 service endpoints and Stage 2 LLM interfaces/endpoints remain available.

## Architecture

```text
POST /api/v1/documents
          |
          v
   DocumentManager
     |    |     |
     |    |     +--> StructureAwareChunker
     |    +--------> PDFProcessor (pypdf)
     +-------------> FileSystemDocumentRepository
                       |-- <sha256>.pdf
                       +-- <document-id>.json
```

The JSON record includes document, page, and chunk data and provenance. Stage 4 can
replace the repository behind `DocumentManager` with PostgreSQL/pgvector without
changing the upload API or PDF/chunking services.

## Project structure

```text
backend/
├── api/routes/documents.py
├── documents/
│   ├── chunking.py
│   ├── errors.py
│   ├── manager.py
│   ├── models.py
│   ├── pdf.py
│   └── repository.py
├── llm/                    # Stage 2 provider abstraction
└── schemas/documents.py

tests/
├── pdf_factory.py
└── unit/
    ├── documents/
    └── test_document_endpoints.py
```

## Prerequisites and local setup

- Python 3.12+
- Docker Desktop only when using Docker
- an OpenAI API key only when intentionally selecting the real OpenAI provider

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest
uvicorn backend.main:app --reload
```

The example environment selects `LLM_PROVIDER="mock"`, so setup and all tests are
key-free. Never commit `.env`, uploaded documents, or API keys.

Useful endpoints:

- service information: `http://127.0.0.1:8000/`
- Swagger: `http://127.0.0.1:8000/docs`
- liveness: `http://127.0.0.1:8000/health`
- readiness: `http://127.0.0.1:8000/ready`
- provider status: `http://127.0.0.1:8000/api/v1/llm/status`
- document upload: `http://127.0.0.1:8000/api/v1/documents`

## Upload a PDF

With curl:

```powershell
curl.exe -X POST `
  -F "file=@C:\path\to\student-handbook.pdf;type=application/pdf" `
  http://127.0.0.1:8000/api/v1/documents
```

Or with PowerShell 7:

```powershell
$form = @{ file = Get-Item "C:\path\to\student-handbook.pdf" }
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/documents `
  -Form $form
```

A successful upload returns `201` with the secure filename, SHA-256 checksum, PDF
metadata, page records, and chunks. Re-uploading identical bytes returns `409
DOCUMENT_DUPLICATE` with the existing document ID.

## Document configuration

| Variable | Default | Purpose |
|---|---:|---|
| `DOCUMENT_STORAGE_PATH` | `data/documents` | controlled directory for PDFs and JSON sidecars |
| `MAX_DOCUMENT_SIZE_BYTES` | `10485760` | maximum accepted upload size (10 MiB) |
| `CHUNK_SIZE` | `1200` | maximum chunk length in characters |
| `CHUNK_OVERLAP` | `200` | contextual character overlap between adjacent chunks |

`CHUNK_OVERLAP` must be smaller than `CHUNK_SIZE`. Accepted content types are
`application/pdf` and `application/x-pdf`; the filename must end in `.pdf`, and the
bytes must carry a valid PDF signature and parse successfully.

The existing provider variables remain supported, including `LLM_PROVIDER`,
`OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_EMBEDDING_MODEL`, timeout/retry settings,
and the non-production smoke-test toggle. The code defaults to OpenAI so missing
production credentials fail readiness; `.env.example` uses mock mode for safe local
development.

## Storage and security behaviour

The client filename is never used as a filesystem path. Path components are
rejected, the display filename is normalised, and stored PDF names are derived only
from the SHA-256 checksum. Repository paths are resolved and checked against the
configured root. Writes use same-directory temporary files followed by atomic
replacement. Runtime storage under `data/` is ignored by Git.

This stage extracts existing PDF text. It deliberately rejects image-only files;
OCR can be introduced later as a separate, resource-controlled pipeline.

## Docker

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose persists uploaded documents through `./data:/app/data`. Stop the service
with `docker compose down`.

## Quality commands

```powershell
pytest
ruff check .
ruff format --check .
```

No test calls OpenAI: endpoint tests use `MockLLMProvider`, and OpenAI provider tests
use local fake clients.

## Stage 4 direction

Stage 4 can add a repository protocol with PostgreSQL document/page/chunk tables,
embed the persisted chunks through the existing `LLMProvider.create_embeddings`,
store vectors in pgvector, and build retrieval with document/page citations. The
stable checksum, chunk IDs, page provenance, headings, and metadata created here are
already suitable for idempotent indexing and traceable RAG responses.
