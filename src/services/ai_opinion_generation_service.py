# -*- coding: utf-8 -*-
"""Execute the phase-2.1 AI opinion generation loop."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.analyzer import GeminiAnalyzer
from src.config import get_config
from src.repositories.ai_opinion_repo import (
    AIOpinionRepository,
    AIOpinionStateTransitionError,
)
from src.services.ai_opinion_context_builder import AnalysisOpinionContextBuilder
from src.services.ai_opinion_prompt_loader import load_prompt
from src.services.ai_opinion_service import AIOpinionNotFoundError, AIOpinionService
from src.services.ai_opinion_validator import (
    AIOpinionSafetyError,
    AIOpinionSchemaError,
    parse_ai_opinion_output,
    render_ai_opinion_content,
    validate_ai_opinion_output,
    parse_ai_opinion_output_v2,
    validate_ai_opinion_output_v2,
    AIOpinionStructuredOutputV2,
    parse_ai_opinion_output,
)
from src.storage import DatabaseManager


class AIOpinionGenerationService:
    """Run one opinion generation attempt against the shared GenerationBackend."""

    PROMPT_NAME = "ai_opinion"
    PROMPT_VERSION = "v2"

    def __init__(
        self,
        *,
        db_manager: Optional[DatabaseManager] = None,
        repo: Optional[AIOpinionRepository] = None,
        opinion_service: Optional[AIOpinionService] = None,
        analyzer: Optional[GeminiAnalyzer] = None,
        context_builder: Optional[AnalysisOpinionContextBuilder] = None,
    ) -> None:
        self.db = db_manager or DatabaseManager.get_instance()
        self.repo = repo or AIOpinionRepository(self.db)
        self.opinion_service = opinion_service or AIOpinionService(repo=self.repo, db_manager=self.db)
        self.analyzer = analyzer or GeminiAnalyzer(config=get_config())
        self.context_builder = context_builder or AnalysisOpinionContextBuilder(self.db)

    def generate(self, opinion_id: int) -> Dict[str, Any]:
        row = self.repo.get(int(opinion_id))
        if row is None:
            raise AIOpinionNotFoundError(f"AI opinion not found: {opinion_id}")
        if row.analysis_history_id is None or row.source_status == "deleted":
            self.repo.mark_failed(int(opinion_id), error_message="source_analysis_history_unavailable")
            raise ValueError("source_analysis_history_unavailable")

        self.repo.mark_generating(int(opinion_id))
        try:
            context = self.context_builder.build(int(row.analysis_history_id))
            prompts = load_prompt(self.PROMPT_NAME, self.PROMPT_VERSION)
            context_json = json.dumps(context.model_dump(mode="json"), ensure_ascii=False, indent=2)
            snapshot_json = row.principle_snapshot_json or "[]"
            user_prompt = prompts["user"].replace("{{CONTEXT_JSON}}", context_json).replace(
                "{{PRINCIPLE_CONTEXT_JSON}}", snapshot_json
            )
            prompt_hash = hashlib.sha256(context_json.encode("utf-8")).hexdigest()
            generation_config = {
                "temperature": 0.2,
                "max_output_tokens": 2200,
            }
            result = self.analyzer._get_generation_backend().generate(
                user_prompt,
                generation_config,
                system_prompt=prompts["system"],
                response_validator=lambda text: self._parse_output_compat(text),
                audit_context={
                    "feature": "ai_opinion_generation",
                    "opinion_id": int(opinion_id),
                    "analysis_history_id": int(row.analysis_history_id),
                },
            )
            parsed = self._parse_output_compat(result.text)
            from types import SimpleNamespace
            snapshot = SimpleNamespace(items=tuple(
                SimpleNamespace(principle_id=item["principle_id"], principle_version=item["principle_version"])
                for item in json.loads(snapshot_json)
            ))
            validate_ai_opinion_output_v2(parsed, context=context, principle_snapshot=snapshot)
            content = render_ai_opinion_content(parsed)
            completed = self.repo.mark_completed(
                int(opinion_id),
                content=content,
                conclusion=parsed.summary,
                output_json=json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False),
                evidence_json=json.dumps(
                    [item.model_dump(mode="json") for item in parsed.supporting_evidence],
                    ensure_ascii=False,
                ),
                risks_json=json.dumps(parsed.risks, ensure_ascii=False),
                limitations_json=json.dumps(parsed.limitations, ensure_ascii=False),
                watch_items_json=json.dumps(parsed.things_to_watch, ensure_ascii=False),
                model=result.model,
                provider=result.provider,
                temperature=float(generation_config["temperature"]),
                prompt_version=f"{self.PROMPT_NAME}-{self.PROMPT_VERSION}",
                audit_metadata_json=json.dumps(
                    {
                        "backend": result.backend,
                        "usage": result.usage,
                        "context_version": context.context_version,
                        "context_stats": {
                            "key_points": len(context.key_points),
                            "risks": len(context.risks),
                            "news_items": len(context.news_evidence),
                        },
                        "source_trace": context.source_trace.model_dump(mode="json"),
                        "supporting_sources": [item.model_dump(mode="json") for item in context.supporting_sources],
                        "truncated": context.truncated,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
                context_hash=prompt_hash,
                generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                principle_assessments={
                    item.principle_id: {
                        "status": item.status,
                        "relevance": item.relevance,
                        "evidence_json": json.dumps([e.model_dump(mode="json") for e in item.evidence], ensure_ascii=False),
                        "explanation": item.explanation,
                        "confidence": item.confidence,
                    }
                    for item in parsed.principle_assessment
                },
            )
            if completed is None:
                raise RuntimeError("ai_opinion_completion_persist_failed")
            return self.opinion_service.get_opinion(completed.id)
        except AIOpinionStateTransitionError:
            raise
        except AIOpinionSafetyError as exc:
            self.repo.mark_rejected(int(opinion_id), error_message=str(exc))
            raise
        except AIOpinionSchemaError as exc:
            self.repo.mark_failed(int(opinion_id), error_message=str(exc))
            raise
        except Exception as exc:
            self.repo.mark_failed(int(opinion_id), error_message=str(exc)[:500])
            raise

    @staticmethod
    def _parse_output_compat(text: str) -> AIOpinionStructuredOutputV2:
        """Accept legacy v1 provider fixtures while emitting the v2 contract."""
        try:
            return parse_ai_opinion_output_v2(text)
        except AIOpinionSchemaError:
            legacy = parse_ai_opinion_output(text)
            payload = legacy.model_dump(mode="json")
            payload["schema_version"] = "ai-opinion-output-v2"
            payload["principle_assessment"] = []
            payload["overall_discipline_summary"] = (
                legacy.investment_discipline_notes[0]
                if legacy.investment_discipline_notes else "no principles"
            )
            return AIOpinionStructuredOutputV2.model_validate(payload)
