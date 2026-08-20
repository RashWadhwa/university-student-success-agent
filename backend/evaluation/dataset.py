"""Load the single configured synthetic evaluation dataset safely."""

import json
from pathlib import Path

from pydantic import ValidationError

from backend.evaluation.errors import EvaluationDatasetError
from backend.evaluation.models import EvaluationCase

STAGE7_DATASET_NAME = "stage7-policy"


class EvaluationDataset:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._cases: tuple[EvaluationCase, ...] | None = None

    @property
    def name(self) -> str:
        return STAGE7_DATASET_NAME

    def load(self) -> tuple[EvaluationCase, ...]:
        if self._cases is not None:
            return self._cases
        try:
            cases = tuple(
                EvaluationCase.model_validate(json.loads(line))
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise EvaluationDatasetError() from exc
        if not cases or len({case.id for case in cases}) != len(cases):
            raise EvaluationDatasetError()
        self._cases = cases
        return cases

    def select(self, case_ids: list[str] | None) -> tuple[EvaluationCase, ...]:
        cases = self.load()
        if not case_ids:
            return cases
        selected = {case.id: case for case in cases if case.id in set(case_ids)}
        if len(selected) != len(case_ids):
            raise EvaluationDatasetError()
        return tuple(selected[case_id] for case_id in case_ids)
