# -*- coding: utf-8 -*-
"""Service layer for versioned AI opinion records."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.repositories.ai_opinion_repo import (
    AIOpinionRepository,
    AIOpinionVersionConflictError,
)
from src.services.ai_opinion_context_builder import AnalysisOpinionContextBuilder
from src.services.history_service import HistoryService
from src.storage import DatabaseManager
from src.utils.data_processing import parse_json_field


AI_OPINION_GENERATION_STATUSES = frozenset({
    "pending",
    "generating",
    "completed",
    "failed",
    "rejected",
})
AI_OPINION_SOURCE_STATUSES = frozenset({"available", "deleted"})
AI_OPINION_FEEDBACK_VALUES = frozenset({"useful", "not_useful"})


class AIOpinionNotFoundError(ValueError):
    """Raised when an AI opinion record does not exist."""


class AIOpinionConflictError(ValueError):
    """Raised when AI opinion version creation conflicts with existing data."""


class AIOpinionSourceUnavailableError(ValueError):
    """Raised when an operation requires a live analysis_history source."""


class AIOpinionContextUnavailableError(ValueError):
    """Raised when analysis_history cannot build a safe AI opinion context."""


class AIOpinionService:
    """Business logic for ai_opinions."""

    def __init__(
        self,
        repo: Optional[AIOpinionRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
        context_builder: Optional[AnalysisOpinionContextBuilder] = None,
    ):
        self.repo = repo or AIOpinionRepository(db_manager)
        self.db = db_manager or getattr(self.repo, "db", None) or DatabaseManager.get_instance()
        self.context_builder = context_builder or AnalysisOpinionContextBuilder(self.db)

    def create_opinion(
        self,
        *,
        analysis_history_id: Any,
        generation_status: Any = "completed",
        title: Optional[Any] = None,
        content: Optional[Any] = None,
        conclusion: Optional[Any] = None,
        output_json: Optional[Any] = None,
        evidence: Optional[Any] = None,
        risks: Optional[Any] = None,
        limitations: Optional[Any] = None,
        watch_items: Optional[Any] = None,
        model: Optional[Any] = None,
        provider: Optional[Any] = None,
        temperature: Optional[Any] = None,
        prompt_version: Optional[Any] = None,
        audit_metadata: Optional[Any] = None,
        is_current: bool = True,
    ) -> Dict[str, Any]:
        history_id = self._normalize_history_id(analysis_history_id)
        if self.db.get_analysis_history_by_id(history_id) is None:
            raise AIOpinionNotFoundError(f"Analysis history not found: {history_id}")
        status = self._normalize_status(generation_status)
        title_text = self._normalize_optional_text(title)
        content_text = self._normalize_optional_text(content)
        conclusion_text = self._normalize_optional_text(conclusion)
        if status == "completed" and not any((title_text, content_text, conclusion_text, output_json)):
            raise ValueError("completed opinion requires title, content, conclusion, or output_json")
        try:
            row = self.repo.create_version(
                {
                    "analysis_history_id": history_id,
                    "generation_status": status,
                    "source_status": "available",
                    "title": title_text,
                    "content": content_text,
                    "conclusion": conclusion_text,
                    "output_json": self._json_dumps(output_json),
                    "evidence_json": self._json_dumps(evidence),
                    "risks_json": self._json_dumps(risks),
                    "limitations_json": self._json_dumps(limitations),
                    "watch_items_json": self._json_dumps(watch_items),
                    "model": self._normalize_optional_text(model),
                    "provider": self._normalize_optional_text(provider),
                    "temperature": self._normalize_optional_float(temperature),
                    "prompt_version": self._normalize_optional_text(prompt_version),
                    "audit_metadata_json": self._json_dumps(audit_metadata),
                    "is_current": bool(is_current),
                }
            )
        except AIOpinionVersionConflictError as exc:
            raise AIOpinionConflictError(str(exc)) from exc
        return self._serialize(row, analysis_history_available=True)

    def create_pending_generation(self, *, analysis_history_id: Any) -> Dict[str, Any]:
        history_id = self._normalize_history_id(analysis_history_id)
        if self.db.get_analysis_history_by_id(history_id) is None:
            raise AIOpinionNotFoundError(f"Analysis history not found: {history_id}")
        try:
            self.context_builder.build(history_id)
        except ValueError as exc:
            raise AIOpinionContextUnavailableError(str(exc)) from exc
        if self.repo.has_inflight_generation(history_id):
            raise AIOpinionConflictError(
                f"AI opinion generation already in progress for analysis_history_id={history_id}"
            )
        try:
            row = self.repo.create_version(
                {
                    "analysis_history_id": history_id,
                    "generation_status": "pending",
                    "source_status": "available",
                    "retry_count": 0,
                    "is_current": False,
                }
            )
        except AIOpinionVersionConflictError as exc:
            raise AIOpinionConflictError(str(exc)) from exc
        return self._serialize(row, analysis_history_available=True)

    def regenerate_opinion(self, opinion_id: Any) -> Dict[str, Any]:
        row = self.repo.get(int(opinion_id))
        if row is None:
            raise AIOpinionNotFoundError(f"AI opinion not found: {opinion_id}")
        if row.analysis_history_id is None or row.source_status == "deleted":
            raise AIOpinionSourceUnavailableError(
                f"AI opinion source analysis_history is unavailable: {opinion_id}"
            )
        return self.create_pending_generation(analysis_history_id=row.analysis_history_id)

    def get_opinion(self, opinion_id: Any) -> Dict[str, Any]:
        row = self.repo.get(int(opinion_id))
        if row is None:
            raise AIOpinionNotFoundError(f"AI opinion not found: {opinion_id}")
        analysis_history_available = (
            row.analysis_history_id is not None
            and self.db.get_analysis_history_by_id(int(row.analysis_history_id)) is not None
        )
        return self._serialize(row, analysis_history_available=analysis_history_available)

    def update_feedback(
        self,
        opinion_id: Any,
        *,
        feedback_value: Any,
        feedback_note: Any = None,
    ) -> Dict[str, Any]:
        normalized_value = str(feedback_value or "").strip().lower()
        if normalized_value not in AI_OPINION_FEEDBACK_VALUES:
            raise ValueError("feedback_value must be useful or not_useful")
        note = self._normalize_optional_text(feedback_note)
        if note and len(note) > 1000:
            raise ValueError("feedback_note must be at most 1000 characters")
        row = self.repo.update_feedback(
            int(opinion_id),
            feedback_value=normalized_value,
            feedback_note=note,
        )
        if row is None:
            raise AIOpinionNotFoundError(f"AI opinion not found: {opinion_id}")
        analysis_history_available = (
            row.analysis_history_id is not None
            and self.db.get_analysis_history_by_id(int(row.analysis_history_id)) is not None
        )
        return self._serialize(row, analysis_history_available=analysis_history_available)

    def list_opinions(
        self,
        *,
        analysis_history_id: Any,
        current_only: bool = False,
        page: Any = 1,
        page_size: Any = 50,
    ) -> Dict[str, Any]:
        history_id = self._normalize_history_id(analysis_history_id)
        if self.db.get_analysis_history_by_id(history_id) is None:
            raise AIOpinionNotFoundError(f"Analysis history not found: {history_id}")
        normalized_page, normalized_page_size = self._normalize_pagination(page, page_size)
        all_items = [
            self._serialize(row, analysis_history_available=True)
            for row in self.repo.list_by_analysis_history(history_id, current_only=current_only)
        ]
        start = (normalized_page - 1) * normalized_page_size
        items = all_items[start:start + normalized_page_size]
        return {
            "items": items,
            "total": len(all_items),
            "page": normalized_page,
            "page_size": normalized_page_size,
        }

    def list_opinions_by_stock(
        self,
        *,
        stock_code: Any,
        current_only: bool = False,
        page: Any = 1,
        page_size: Any = 50,
    ) -> Dict[str, Any]:
        normalized_codes = self._normalize_stock_codes(stock_code)
        normalized_page, normalized_page_size = self._normalize_pagination(page, page_size)
        rows, total = self.repo.list_by_stock_codes(
            normalized_codes,
            current_only=current_only,
            page=normalized_page,
            page_size=normalized_page_size,
        )

        items = [
            self._serialize(row, analysis_history_available=True, analysis_history=history)
            for row, history in rows
        ]
        return {
            "items": items,
            "total": total,
            "page": normalized_page,
            "page_size": normalized_page_size,
        }

    @staticmethod
    def _serialize(row, *, analysis_history_available: bool, analysis_history=None) -> Dict[str, Any]:
        payload = {
            "id": row.id,
            "analysis_history_id": row.analysis_history_id,
            "analysis_history_available": bool(analysis_history_available),
            "version": row.version,
            "is_current": row.is_current,
            "generation_status": row.generation_status,
            "source_status": row.source_status,
            "title": row.title,
            "content": row.content,
            "conclusion": row.conclusion,
            "output_json": parse_json_field(row.output_json),
            "evidence": parse_json_field(row.evidence_json),
            "risks": parse_json_field(row.risks_json),
            "limitations": parse_json_field(row.limitations_json),
            "watch_items": parse_json_field(row.watch_items_json),
            "model": row.model,
            "provider": row.provider,
            "temperature": row.temperature,
            "prompt_version": row.prompt_version,
            "audit_metadata": parse_json_field(row.audit_metadata_json),
            "error_message": row.error_message,
            "context_hash": row.context_hash,
            "retry_count": row.retry_count,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "feedback_value": row.feedback_value,
            "feedback_note": row.feedback_note,
            "feedback_updated_at": row.feedback_updated_at.isoformat()
            if row.feedback_updated_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        if analysis_history is not None:
            payload.update({
                "analysis_stock_code": analysis_history.code,
                "analysis_stock_name": analysis_history.name,
                "analysis_created_at": analysis_history.created_at.isoformat()
                if analysis_history.created_at else None,
            })
        return payload

    @staticmethod
    def _normalize_history_id(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError("analysis_history_id must be a positive integer") from None
        if parsed <= 0:
            raise ValueError("analysis_history_id must be a positive integer")
        return parsed

    @staticmethod
    def _normalize_pagination(page: Any, page_size: Any) -> tuple[int, int]:
        try:
            normalized_page = int(page)
            normalized_page_size = int(page_size)
        except (TypeError, ValueError):
            raise ValueError("page and page_size must be positive integers") from None
        if normalized_page <= 0 or normalized_page_size <= 0:
            raise ValueError("page and page_size must be positive integers")
        return normalized_page, min(normalized_page_size, 100)

    @staticmethod
    def _normalize_stock_code(value: Any) -> str:
        code = str(value or "").strip().upper()
        if not code:
            raise ValueError("stock_code is required")
        return code

    @classmethod
    def _normalize_stock_codes(cls, value: Any) -> List[str]:
        code = cls._normalize_stock_code(value)
        candidates = HistoryService._history_code_filter_candidates(code)
        if code not in candidates:
            candidates.append(code)
        return candidates

    @staticmethod
    def _normalize_status(value: Any) -> str:
        status = str(value or "").strip().lower()
        if status not in AI_OPINION_GENERATION_STATUSES:
            allowed = ", ".join(sorted(AI_OPINION_GENERATION_STATUSES))
            raise ValueError(f"generation_status must be one of {allowed}")
        return status

    @staticmethod
    def _normalize_optional_text(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_optional_float(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError("temperature must be a number") from None

    @staticmethod
    def _json_dumps(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                json.loads(value)
                return value
            except Exception:
                pass
        return json.dumps(value, ensure_ascii=False, default=str)
