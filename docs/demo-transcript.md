# University Student Success Agent — Demo Transcript

## Opening

The University Student Success Agent helps students understand assessment policies
without pretending to make university decisions. It retrieves current evidence,
generates bounded guidance, verifies citations, and escalates uncertainty to people.

## Diagram walkthrough

### 1. Architecture

Start with the README's [high-level system flow](../README.md#high-level-system-flow).
Streamlit is an unprivileged HTTP client; FastAPI owns validation and the baseline and
agentic workflows. RAG services use PostgreSQL/pgvector and replaceable model providers,
while Langfuse receives only safe cross-cutting metadata.

Stages 1 and 2 established the API and provider abstraction. Stage 3 added safe PDF
ingestion, Stage 4 hybrid retrieval, Stage 5 grounded answers, Stage 6 bounded agents,
and Stage 7 the portal, evaluation, and privacy-safe observability.

### 2. RAG

Move to the [RAG flow](../README.md#rag-and-grounded-answer-flow). A PDF passes through
type, size, encryption, corruption, and text checks before structure-aware chunking.
Embeddings and metadata are indexed atomically; hybrid vector/full-text retrieval feeds
only bounded evidence to grounded generation, followed by deterministic citation and
claim verification.

The configured institution supplies default indexing and retrieval metadata. The
primary corpus is official institution policy; secondary official UK guidance remains
clearly labelled by publisher, source URL, corpus tier, and authority scope.

### 3. Agents

Use the [agentic workflow](../README.md#agentic-workflow) to show one fixed acyclic
sequence: Coordinator, Retrieval Specialist, Policy Analyst, Student Support
Specialist, and Verifier. The coordinator plans once, hard budgets prevent loops, and
the verifier can terminate only as `completed`, `escalated`, or `failed`.

### 4. Evaluation

Use the [evaluation flow](../README.md#evaluation-flow). Baseline and agentic workflows
run against the same versioned synthetic dataset. Deterministic metrics remain separate
from the independent Gemini judge, safe request/trace IDs correlate the runs, and the
comparison reports wins and ties without assuming the agentic workflow is better.

### 5. Security

Use the [security/data-boundary diagram](../README.md#security-and-data-boundaries).
The browser and Streamlit receive no database credentials or model keys. FastAPI
validates bounded inputs, application services keep the public policy corpus separate
from future private case data, and PII redaction runs before Langfuse. Authentication
and RLS-protected private records are explicitly Stage 8 work, not a Stage 7 claim.

### 6. Deployment

Finish the diagram sequence with the [deployment flow](../README.md#deployment-flow):
the user reaches Render Streamlit, Streamlit calls Render FastAPI over HTTPS, and
FastAPI alone connects to Supabase PostgreSQL/pgvector, generation providers, the
Gemini judge, and Langfuse EU. Secrets remain server-side.

## Live demo

1. Open **Ask for Support**, point out that the institution label came from safe public
   backend configuration, select “Missed Assessment,” and choose Agentic mode.
2. Show the grounded answer, next actions, confidence, limitations, and human-support
   recommendation.
3. Expand a citation to show its title, section, page, version, effective date, public
   source, and bounded excerpt.
4. Open **Agent Activity** and show safe milestones and terminal state—never prompts,
   hidden reasoning, or private agent messages.
5. Show the request ID and privacy-safe Langfuse trace ID correlation.
6. Open **Evidence Explorer** to inspect hybrid retrieval without embeddings or SQL.
7. Open **Evaluation**, select Both, and explicitly run the synthetic dataset. Compare
   groundedness, citation accuracy, policy correctness, escalation accuracy, latency,
   provider calls, and tool calls. The result reports baseline wins and ties.
8. Open **System** to show safe component status without credentials or raw errors.

## Evaluation narration

“An independent Gemini 3.1 Flash Lite judge evaluates groundedness, policy correctness, completeness, and escalation quality, while deterministic checks continue to validate citations and other rules that do not require an LLM judge.”

Only synthetic questions, expected criteria, generated answers, bounded evidence
excerpts, and citation metadata reach the judge. Automated tests use a deterministic
mock and never call paid providers.

## Security close

Questions, full answers, documents, evidence bodies, prompts, sessions, student
identifiers, credentials, and connection strings are rejected from traces. Langfuse
failure degrades safely, evaluation failure cannot affect student support, and the
liveness probe remains independent of all external services.
