"""Single controlled workflow for grounded student policy guidance."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit

from backend.ask.errors import AskValidationError
from backend.ask.evidence import assess_evidence
from backend.ask.models import GroundedAnswerOutput
from backend.ask.prompts import build_grounded_prompt
from backend.ask.scope import assess_scope
from backend.ask.types import (
    AskOutcome,
    AskResult,
    Citation,
    Confidence,
    Evidence,
    EvidenceAssessment,
    RecommendedAction,
)
from backend.ask.verification import verify_grounded_output
from backend.core.context import get_request_id
from backend.llm.base import GenerationOptions, LLMProvider
from backend.llm.errors import LLMError
from backend.rag.errors import RetrievalUnavailableError
from backend.rag.retrieval import RetrievalService
from backend.rag.types import SearchFilters

logger = logging.getLogger(__name__)


class AskService:
    """Orchestrate scope, retrieval, generation, verification, and escalation."""

    def __init__(
        self,
        *,
        retrieval: RetrievalService,
        provider: LLMProvider,
        default_top_k: int,
        max_top_k: int,
        minimum_evidence_count: int,
        minimum_retrieval_score: float,
        maximum_evidence_chunks: int,
        evidence_max_chars_per_chunk: int,
        maximum_question_chars: int,
        citation_excerpt_max_chars: int,
    ) -> None:
        self.retrieval = retrieval
        self.provider = provider
        self.default_top_k = default_top_k
        self.max_top_k = max_top_k
        self.minimum_evidence_count = minimum_evidence_count
        self.minimum_retrieval_score = minimum_retrieval_score
        self.maximum_evidence_chunks = maximum_evidence_chunks
        self.evidence_max_chars_per_chunk = evidence_max_chars_per_chunk
        self.maximum_question_chars = maximum_question_chars
        self.citation_excerpt_max_chars = citation_excerpt_max_chars

    async def answer(
        self,
        *,
        question: str,
        top_k: int | None,
        filters: SearchFilters,
        session_id: str | None = None,
    ) -> AskResult:
        """Return an answered or deterministic safe-fallback result."""

        del session_id  # accepted for forward compatibility; durable memory is Stage 6+
        started = perf_counter()
        request_id = get_request_id()
        cleaned_question = question.strip()
        resolved_top_k = top_k if top_k is not None else self.default_top_k
        self._validate(cleaned_question, resolved_top_k)
        logger.info("ask_received", extra={"query_length": len(cleaned_question)})

        scope = assess_scope(cleaned_question)
        logger.info(
            "ask_scope_checked",
            extra={
                "supported": scope.supported,
                "requires_individual_decision": scope.requires_individual_decision,
            },
        )
        if not scope.supported:
            return self._complete(
                self._fallback(
                    outcome=AskOutcome.UNSUPPORTED,
                    answer=(
                        "I can currently help only with university assessment policy, including "
                        "missed or late assessments, extensions, mitigating circumstances, "
                        "reassessment, and academic appeals."
                    ),
                    reason=scope.reason,
                    request_id=request_id,
                ),
                started,
            )

        try:
            results = await self.retrieval.search(
                query=cleaned_question,
                top_k=resolved_top_k,
                filters=filters,
                minimum_score=self.minimum_retrieval_score,
                prefer_recent=True,
            )
        except (RetrievalUnavailableError, LLMError, TimeoutError) as exc:
            logger.warning(
                "ask_retrieval_failed",
                extra={"error_type": type(exc).__name__},
            )
            return self._complete(
                self._fallback(
                    outcome=AskOutcome.TEMPORARILY_UNAVAILABLE,
                    answer=(
                        "I cannot check the indexed university policy evidence right now. "
                        "Please try again later or contact the appropriate university support team."
                    ),
                    reason="The policy retrieval service is temporarily unavailable.",
                    request_id=request_id,
                ),
                started,
            )
        logger.info("ask_retrieval_completed", extra={"retrieved_count": len(results)})

        assessment = assess_evidence(
            results,
            question=cleaned_question,
            minimum_count=self.minimum_evidence_count,
            minimum_score=self.minimum_retrieval_score,
            maximum_chunks=self.maximum_evidence_chunks,
        )
        if not assessment.sufficient:
            logger.info(
                "ask_evidence_insufficient",
                extra={
                    "retrieved_count": len(results),
                    "evidence_count": len(assessment.evidence),
                    "conflicting": assessment.conflicting,
                },
            )
            return self._complete(
                self._evidence_fallback(assessment, len(results), request_id),
                started,
            )

        system_prompt, user_prompt = build_grounded_prompt(
            cleaned_question,
            assessment.evidence,
            max_chars_per_chunk=self.evidence_max_chars_per_chunk,
        )
        logger.info(
            "ask_generation_started",
            extra={"evidence_count": len(assessment.evidence)},
        )
        try:
            generated = await self.provider.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=GroundedAnswerOutput,
                options=GenerationOptions(),
            )
        except (LLMError, TimeoutError) as exc:
            logger.warning(
                "ask_generation_failed",
                extra={"error_type": type(exc).__name__},
            )
            return self._complete(
                self._fallback(
                    outcome=AskOutcome.TEMPORARILY_UNAVAILABLE,
                    answer=(
                        "I found relevant policy evidence but could not produce a verified answer "
                        "right now. Please try again later or ask university staff for guidance."
                    ),
                    reason="The answer-generation service is temporarily unavailable.",
                    request_id=request_id,
                    retrieved_count=len(results),
                    evidence_count=len(assessment.evidence),
                ),
                started,
            )
        logger.info(
            "ask_generation_completed",
            extra={"provider": generated.provider, "model": generated.model},
        )

        verification = verify_grounded_output(generated.output, assessment.evidence)
        logger.info(
            "ask_citation_verification_completed",
            extra={
                "verified": verification.valid,
                "citation_count": len(verification.citation_ids),
            },
        )
        if not verification.valid:
            logger.info(
                "ask_escalation_triggered",
                extra={"reason": "citation_verification_failed"},
            )
            return self._complete(
                self._fallback(
                    outcome=AskOutcome.VERIFICATION_FAILED,
                    answer=(
                        "I found policy evidence, but I could not verify the generated guidance "
                        "against it. Please consult the relevant university support team."
                    ),
                    reason="The answer's policy citations could not be verified.",
                    request_id=request_id,
                    retrieved_count=len(results),
                    evidence_count=len(assessment.evidence),
                ),
                started,
            )

        confidence = self._confidence(assessment)
        requires_human = (
            scope.requires_individual_decision or generated.output.requires_human_support
        )
        human_reason = None
        if scope.requires_individual_decision:
            confidence = Confidence.LOW
            requires_human = True
            human_reason = (
                "University staff must make decisions about individual eligibility or approval."
            )
        elif generated.output.requires_human_support:
            human_reason = (
                "The available policy guidance does not resolve all aspects of the individual case."
            )

        limitations = list(generated.output.limitations)
        if assessment.older_versions_omitted:
            limitations.append(
                "Older retrieved policy versions were omitted in favour of the latest "
                "effective evidence."
            )
        result = AskResult(
            outcome=AskOutcome.ANSWERED,
            answer=generated.output.answer,
            recommended_actions=tuple(
                RecommendedAction(
                    priority=item.priority,
                    action=item.action,
                    reason=item.reason,
                )
                for item in sorted(
                    generated.output.recommended_actions,
                    key=lambda action: action.priority,
                )
            ),
            citations=tuple(
                self._citation(self._evidence_by_id(assessment)[citation_id])
                for citation_id in verification.citation_ids
            ),
            confidence=confidence,
            limitations=tuple(dict.fromkeys(limitations)),
            requires_human_support=requires_human,
            human_support_reason=human_reason,
            request_id=request_id,
            retrieved_count=len(results),
            evidence_count=len(assessment.evidence),
            citation_verification_passed=True,
            evaluation={
                "retrieval_strength": round(assessment.max_score, 4),
                "citation_count": len(verification.citation_ids),
                "citation_verification_passed": True,
                "confidence": confidence.value,
                "requires_human_support": requires_human,
            },
        )
        if requires_human:
            logger.info("ask_escalation_triggered", extra={"reason": "individual_support"})
        return self._complete(result, started)

    def _validate(self, question: str, top_k: int) -> None:
        if not question:
            raise AskValidationError(details={"field": "question", "reason": "blank"})
        if len(question) > self.maximum_question_chars:
            raise AskValidationError(
                details={
                    "field": "question",
                    "maximum_chars": self.maximum_question_chars,
                }
            )
        if not 1 <= top_k <= self.max_top_k:
            raise AskValidationError(
                details={"field": "top_k", "minimum": 1, "maximum": self.max_top_k}
            )

    def _evidence_fallback(
        self,
        assessment: EvidenceAssessment,
        retrieved_count: int,
        request_id: str,
    ) -> AskResult:
        if assessment.conflicting:
            answer = (
                "The retrieved university policy passages conflict, so I cannot determine which "
                "rule applies. Please ask the relevant university team to confirm the current "
                "policy."
            )
            reason = "Conflicting current policy evidence requires human clarification."
        else:
            answer = (
                "I could not find enough reliable university policy evidence to answer safely. "
                "Please check the current policy or contact the relevant university support team."
            )
            reason = (
                assessment.reasons[0] if assessment.reasons else "Policy evidence was insufficient."
            )
        logger.info("ask_escalation_triggered", extra={"reason": "insufficient_evidence"})
        return self._fallback(
            outcome=AskOutcome.INSUFFICIENT_EVIDENCE,
            answer=answer,
            reason=reason,
            request_id=request_id,
            retrieved_count=retrieved_count,
            evidence_count=len(assessment.evidence),
            limitations=assessment.reasons,
            citations=tuple(self._citation(item) for item in assessment.evidence),
            retrieval_strength=assessment.max_score,
        )

    def _fallback(
        self,
        *,
        outcome: AskOutcome,
        answer: str,
        reason: str | None,
        request_id: str,
        retrieved_count: int = 0,
        evidence_count: int = 0,
        limitations: tuple[str, ...] = (),
        citations: tuple[Citation, ...] = (),
        retrieval_strength: float = 0.0,
    ) -> AskResult:
        return AskResult(
            outcome=outcome,
            answer=answer,
            recommended_actions=(),
            citations=citations,
            confidence=Confidence.LOW,
            limitations=limitations,
            requires_human_support=True,
            human_support_reason=reason,
            request_id=request_id,
            retrieved_count=retrieved_count,
            evidence_count=evidence_count,
            citation_verification_passed=False,
            evaluation={
                "retrieval_strength": round(retrieval_strength, 4),
                "citation_count": len(citations),
                "citation_verification_passed": False,
                "confidence": Confidence.LOW.value,
                "requires_human_support": True,
            },
        )

    def _citation(self, evidence: Evidence) -> Citation:
        excerpt = re.sub(r"\s+", " ", evidence.content).strip()
        if len(excerpt) > self.citation_excerpt_max_chars:
            excerpt = excerpt[: self.citation_excerpt_max_chars].rsplit(" ", 1)[0].rstrip()
            excerpt = f"{excerpt}…"
        return Citation(
            citation_id=evidence.citation_id,
            document_id=evidence.document_id,
            chunk_id=evidence.chunk_id,
            document_title=evidence.title,
            section=evidence.section,
            page=evidence.page,
            source=self._safe_public_source(evidence.source),
            excerpt=excerpt,
            version=evidence.version,
            effective_date=evidence.effective_date,
            retrieval_sources=evidence.retrieval_sources,
        )

    def _confidence(self, assessment: EvidenceAssessment) -> Confidence:
        has_dual_source = any(
            {"semantic", "keyword"} <= set(item.retrieval_sources) for item in assessment.evidence
        )
        high_threshold = max(0.75, self.minimum_retrieval_score + 0.2)
        if (
            len(assessment.evidence) >= 2
            and assessment.max_score >= high_threshold
            and has_dual_source
            and not assessment.older_versions_omitted
        ):
            return Confidence.HIGH
        return Confidence.MEDIUM

    @staticmethod
    def _evidence_by_id(assessment: EvidenceAssessment) -> dict[str, Evidence]:
        return {item.citation_id: item for item in assessment.evidence}

    @staticmethod
    def _safe_public_source(source: str | None) -> str | None:
        """Return only credential-free HTTP(S) citation sources."""

        if source is None:
            return None
        try:
            parsed = urlsplit(source)
        except ValueError:
            return None
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))

    @staticmethod
    def _complete(result: AskResult, started: float) -> AskResult:
        logger.info(
            "ask_completed",
            extra={
                "outcome": result.outcome.value,
                "retrieved_count": result.retrieved_count,
                "evidence_count": result.evidence_count,
                "confidence": result.confidence.value,
                "citation_count": len(result.citations),
                "requires_human_support": result.requires_human_support,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return result
