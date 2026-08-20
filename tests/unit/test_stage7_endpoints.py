"""Typed evaluation and safe system-status API tests."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.evaluation.dataset import EvaluationDataset
from backend.evaluation.models import (
    EvaluationAggregate,
    EvaluationRunResult,
    EvaluationWorkflow,
)


class FakeEvaluationRunner:
    def __init__(self) -> None:
        self.dataset = EvaluationDataset(Path("data/evaluation/stage7-policy-cases.jsonl"))
        self.calls: list[dict[str, object]] = []

    async def run(self, **kwargs: object) -> EvaluationRunResult:
        self.calls.append(kwargs)
        return EvaluationRunResult(
            dataset="stage7-policy",
            workflow=EvaluationWorkflow.BOTH,
            case_count=1,
            judge_calls=2,
            status="completed",
            results=[],
            summaries=[
                EvaluationAggregate(
                    workflow_mode="baseline",
                    case_count=1,
                    passed_count=1,
                    partial_count=0,
                    failed_count=0,
                    deterministic={"citation_validity": 1.0},
                    judge={"groundedness": 0.9},
                    mean_latency_ms=10,
                    total_provider_calls=2,
                    total_tool_calls=0,
                ),
                EvaluationAggregate(
                    workflow_mode="agentic",
                    case_count=1,
                    passed_count=1,
                    partial_count=0,
                    failed_count=0,
                    deterministic={"citation_validity": 1.0},
                    judge={"groundedness": 0.9},
                    mean_latency_ms=15,
                    total_provider_calls=3,
                    total_tool_calls=1,
                ),
            ],
            winner="tie",
        )


def test_evaluation_dataset_listing_is_safe_and_bounded(
    app: FastAPI,
    client: TestClient,
) -> None:
    app.state.evaluation_runner = FakeEvaluationRunner()

    response = client.get("/api/v1/evaluations/datasets")

    assert response.status_code == 200
    dataset = response.json()["datasets"][0]
    assert dataset["name"] == "stage7-policy"
    assert 30 <= dataset["case_count"] <= 50
    assert "question" not in response.text.casefold()


def test_explicit_evaluation_run_calls_runner_once(
    app: FastAPI,
    client: TestClient,
) -> None:
    runner = FakeEvaluationRunner()
    app.state.evaluation_runner = runner

    response = client.post(
        "/api/v1/evaluations/run",
        json={"dataset": "stage7-policy", "workflow": "both"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["winner"] == "tie"
    assert runner.calls == [{"workflow": EvaluationWorkflow.BOTH, "case_ids": None}]


def test_evaluation_request_rejects_unknown_dataset_and_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/evaluations/run",
        json={"dataset": "../../private", "workflow": "both", "sql": "SELECT *"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_system_status_exposes_only_safe_component_metadata(client: TestClient) -> None:
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "fastapi",
        "database",
        "pgvector",
        "primary_llm",
        "langfuse",
        "evaluation",
    }
    assert body["primary_llm"]["provider"] == "mock"
    assert body["evaluation"]["provider"] == "mock"
    serialized = response.text.casefold()
    assert "api_key" not in serialized
    assert "password" not in serialized
    assert "database_url" not in serialized
    assert "postgresql://" not in serialized
