# -*- coding: utf-8 -*-
"""Service layer for stock investment journal entries."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.core.trading_calendar import get_market_for_stock
from src.repositories.ai_opinion_repo import AIOpinionRepository
from src.repositories.investment_journal_repo import (
    InvestmentJournalMutationConflictError,
    InvestmentJournalRepository,
)
from src.services.decision_signal_service import DecisionSignalService
from src.services.portfolio_service import VALID_MARKETS
from src.storage import AnalysisHistory, DatabaseManager, InvestmentJournalEntry
from src.utils.data_processing import parse_json_field


JOURNAL_ENTRY_TYPES = frozenset({"analysis", "manual"})
JOURNAL_SOURCE_STATUSES = frozenset({"available", "deleted"})
AI_PROCESSING_STATUSES = frozenset({
    "not_applicable",
    "pending",
    "processing",
    "succeeded",
    "completed",
    "failed",
})
MAX_MANUAL_RAW_CONTENT_LENGTH = 20000
MAX_SUMMARY_SNAPSHOT_LENGTH = 4000


class InvestmentJournalNotFoundError(ValueError):
    """Raised when a journal entry does not exist."""


class InvestmentJournalUnsupportedHistoryError(ValueError):
    """Raised when a history record should not create a journal entry."""


class InvestmentJournalConflictError(ValueError):
    """Raised when a journal mutation conflicts with entry type semantics."""


class InvestmentJournalStructuringUnavailableError(ValueError):
    """Raised when a journal entry cannot build a valid structuring context."""


class InvestmentJournalService:
    """Business logic for stock investment journals."""

    def __init__(
        self,
        repo: Optional[InvestmentJournalRepository] = None,
        ai_opinion_repo: Optional[AIOpinionRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
    ):
        self.repo = repo or InvestmentJournalRepository(db_manager)
        self.ai_opinion_repo = ai_opinion_repo or AIOpinionRepository(db_manager)
        self.db = db_manager or getattr(self.repo, "db", None) or DatabaseManager.get_instance()

    def sync_analysis_entry(self, analysis_history_id: int) -> Dict[str, Any]:
        record = self._get_analysis_history(analysis_history_id)
        entry_fields = self._build_analysis_entry_fields(record)
        result = self.repo.create_analysis_entry_if_absent(entry_fields)
        return {
            "item": self._serialize_entry(result.row, analysis_history=record),
            "created": result.created,
        }

    def create_manual_entry(
        self,
        *,
        stock_code: Any,
        market: Any,
        raw_content: Any,
        summary_snapshot: Optional[Any] = None,
    ) -> Dict[str, Any]:
        stock_code_norm = self._normalize_stock_code(stock_code, market=market)
        market_norm = self._normalize_market(market)
        raw_content_text = self._normalize_required_text(
            raw_content,
            "raw_content",
            max_length=MAX_MANUAL_RAW_CONTENT_LENGTH,
        )
        summary_text = self._normalize_optional_text(summary_snapshot, max_length=MAX_SUMMARY_SNAPSHOT_LENGTH)
        row = self.repo.create(
            {
                "stock_code": stock_code_norm,
                "market": market_norm,
                "entry_type": "manual",
                "raw_content": raw_content_text,
                "summary_snapshot": summary_text,
                "source_label": "manual_note",
                "source_status": "available",
                "ai_processing_status": "pending",
            }
        )
        return self._serialize_entry(row)

    def get_entry(self, entry_id: int) -> Dict[str, Any]:
        row = self.repo.get(int(entry_id))
        if row is None:
            raise InvestmentJournalNotFoundError(f"Investment journal entry not found: {entry_id}")
        analysis_history = None
        if row.source_analysis_history_id:
            analysis_history = self.db.get_analysis_history_by_id(int(row.source_analysis_history_id))
        return self._serialize_entry(row, analysis_history=analysis_history)

    def list_entries(
        self,
        *,
        stock_code: Any,
        market: Any,
        entry_type: Optional[Any] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        market_norm = self._normalize_market(market)
        stock_code_norm = self._normalize_stock_code(stock_code, market=market_norm)
        entry_type_norm = self._normalize_optional_entry_type(entry_type)
        rows, total = self.repo.list_by_stock(
            stock_code=stock_code_norm,
            market=market_norm,
            entry_type=entry_type_norm,
            page=page,
            page_size=page_size,
        )
        analysis_ids = sorted({
            int(row.source_analysis_history_id)
            for row in rows
            if row.source_analysis_history_id is not None
        })
        analysis_records = {
            history_id: self.db.get_analysis_history_by_id(history_id)
            for history_id in analysis_ids
        }
        current_opinions = {
            history_id: self.ai_opinion_repo.get_current_by_analysis_history(history_id)
            for history_id in analysis_ids
        }
        items = [
            self._serialize_entry(
                row,
                analysis_history=analysis_records.get(int(row.source_analysis_history_id))
                if row.source_analysis_history_id is not None else None,
                current_ai_opinion=current_opinions.get(int(row.source_analysis_history_id))
                if row.source_analysis_history_id is not None else None,
            )
            for row in rows
        ]
        return {
            "items": items,
            "total": total,
            "page": max(1, int(page)),
            "page_size": max(1, min(int(page_size), 100)),
        }

    def update_manual_entry(
        self,
        entry_id: int,
        *,
        raw_content: Optional[Any] = None,
        summary_snapshot: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if raw_content is None and summary_snapshot is None:
            raise ValueError("at least one field must be provided")
        try:
            row = self.repo.update_manual_entry(
                int(entry_id),
                raw_content=None if raw_content is None else self._normalize_required_text(
                    raw_content,
                    "raw_content",
                    max_length=MAX_MANUAL_RAW_CONTENT_LENGTH,
                ),
                summary_snapshot=None if summary_snapshot is None else self._normalize_optional_text(
                    summary_snapshot,
                    max_length=MAX_SUMMARY_SNAPSHOT_LENGTH,
                ),
            )
        except InvestmentJournalMutationConflictError as exc:
            raise InvestmentJournalConflictError(str(exc)) from exc
        if row is None:
            raise InvestmentJournalNotFoundError(f"Investment journal entry not found: {entry_id}")
        return self._serialize_entry(row)

    def create_pending_structuring(self, entry_id: int) -> Dict[str, Any]:
        row = self.repo.get(int(entry_id))
        if row is None:
            raise InvestmentJournalNotFoundError(f"Investment journal entry not found: {entry_id}")
        if row.entry_type != "manual":
            raise InvestmentJournalConflictError("only manual journal entries can be structured")
        current_status = self._normalize_processing_status(row.ai_processing_status)
        if current_status == "processing":
            raise InvestmentJournalConflictError(
                f"journal structuring already in progress for entry_id={int(entry_id)}"
            )
        if not str(row.raw_content or "").strip():
            raise InvestmentJournalStructuringUnavailableError(
                "investment journal entry has no raw_content to structure"
            )
        refreshed = self.repo.reset_structuring(int(entry_id))
        if refreshed is None:
            raise InvestmentJournalNotFoundError(f"Investment journal entry not found: {entry_id}")
        return self._serialize_entry(refreshed)

    def retry_structuring(self, entry_id: int) -> Dict[str, Any]:
        row = self.repo.get(int(entry_id))
        if row is None:
            raise InvestmentJournalNotFoundError(f"Investment journal entry not found: {entry_id}")
        if row.entry_type != "manual":
            raise InvestmentJournalConflictError("only manual journal entries can be structured")
        current_status = self._normalize_processing_status(row.ai_processing_status)
        if current_status in {"pending", "processing"}:
            raise InvestmentJournalConflictError(
                f"journal structuring already in progress for entry_id={int(entry_id)}"
            )
        if not str(row.raw_content or "").strip():
            raise InvestmentJournalStructuringUnavailableError(
                "investment journal entry has no raw_content to structure"
            )
        refreshed = self.repo.reset_structuring(int(entry_id))
        if refreshed is None:
            raise InvestmentJournalNotFoundError(f"Investment journal entry not found: {entry_id}")
        return self._serialize_entry(refreshed)

    def _get_analysis_history(self, analysis_history_id: int) -> AnalysisHistory:
        record = self.db.get_analysis_history_by_id(int(analysis_history_id))
        if record is None:
            raise InvestmentJournalNotFoundError(
                f"Analysis history not found: {analysis_history_id}"
            )
        if self._is_unsupported_history_record(record):
            raise InvestmentJournalUnsupportedHistoryError(
                "analysis_history record is not a single-stock analysis entry"
            )
        return record

    @staticmethod
    def _is_unsupported_history_record(record: AnalysisHistory) -> bool:
        code = str(getattr(record, "code", "") or "").strip().upper()
        report_type = str(getattr(record, "report_type", "") or "").strip().lower()
        return not code or code == "MARKET" or report_type == "market_review"

    def _build_analysis_entry_fields(self, record: AnalysisHistory) -> Dict[str, Any]:
        normalized_code = self._normalize_stock_code(record.code)
        market = self._normalize_market(get_market_for_stock(normalized_code) or "cn")
        summary_snapshot = self._first_text(
            getattr(record, "analysis_summary", None),
            self._extract_from_raw_result(record.raw_result, "analysis_summary"),
        )
        risk_summary = self._first_text(
            self._extract_from_raw_result(record.raw_result, "risk_summary"),
            self._extract_from_raw_result(record.raw_result, "risk"),
            self._extract_from_raw_result(record.raw_result, "risks"),
        )
        watch_items = self._extract_watch_items(record.raw_result)
        created_at = getattr(record, "created_at", None)
        return {
            "stock_code": normalized_code,
            "market": market,
            "entry_type": "analysis",
            "source_analysis_history_id": int(record.id),
            "summary_snapshot": summary_snapshot,
            "risk_summary": risk_summary,
            "watch_items_json": self._json_dumps(watch_items) if watch_items else None,
            "source_label": "analysis_history",
            "source_status": "available",
            "ai_processing_status": "not_applicable",
            "created_at": created_at,
            "updated_at": created_at,
        }

    def _serialize_entry(
        self,
        row: InvestmentJournalEntry,
        *,
        analysis_history: Optional[AnalysisHistory] = None,
        current_ai_opinion: Any = None,
    ) -> Dict[str, Any]:
        item = {
            "id": row.id,
            "stock_code": row.stock_code,
            "market": row.market,
            "entry_type": row.entry_type,
            "source_analysis_history_id": row.source_analysis_history_id,
            "source_status": row.source_status,
            "raw_content": row.raw_content,
            "summary_snapshot": row.summary_snapshot,
            "risk_summary": row.risk_summary,
            "watch_items": parse_json_field(row.watch_items_json),
            "source_label": row.source_label,
            "structured_output": parse_json_field(row.structured_output_json),
            "ai_processing_status": self._normalize_processing_status(row.ai_processing_status),
            "model": row.model,
            "provider": row.provider,
            "temperature": row.temperature,
            "prompt_version": row.prompt_version,
            "structured_version": row.structured_version,
            "structured_at": row.structured_at.isoformat() if row.structured_at else None,
            "structured_error": row.structured_error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        if analysis_history is not None:
            item["analysis_history"] = {
                "id": analysis_history.id,
                "query_id": analysis_history.query_id,
                "report_type": analysis_history.report_type,
                "created_at": analysis_history.created_at.isoformat()
                if analysis_history.created_at else None,
            }
        else:
            item["analysis_history"] = None
        item["analysis_history_available"] = analysis_history is not None
        if current_ai_opinion is not None:
            item["current_ai_opinion"] = {
                "id": current_ai_opinion.id,
                "analysis_history_id": current_ai_opinion.analysis_history_id,
                "version": current_ai_opinion.version,
                "generation_status": current_ai_opinion.generation_status,
                "conclusion": current_ai_opinion.conclusion,
                "created_at": current_ai_opinion.created_at.isoformat()
                if current_ai_opinion.created_at else None,
            }
        else:
            item["current_ai_opinion"] = None
        return item

    @staticmethod
    def _extract_from_raw_result(raw_result: Any, key: str) -> Optional[str]:
        payload = parse_json_field(raw_result)
        if not isinstance(payload, dict):
            return None
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip() or None
        for container_key in ("summary", "dashboard"):
            container = payload.get(container_key)
            if isinstance(container, dict):
                nested = container.get(key)
                if nested not in (None, ""):
                    return str(nested).strip() or None
        return None

    @classmethod
    def _extract_watch_items(cls, raw_result: Any) -> List[str]:
        payload = parse_json_field(raw_result)
        if not isinstance(payload, dict):
            return []
        candidates = []
        for key in ("watch_items", "watch_points", "attention_points", "risks", "risk_factors"):
            value = payload.get(key)
            if value is not None:
                candidates.append(value)
            for container_key in ("summary", "dashboard"):
                container = payload.get(container_key)
                if isinstance(container, dict) and container.get(key) is not None:
                    candidates.append(container.get(key))
        items: List[str] = []
        for value in candidates:
            if isinstance(value, str):
                text = value.strip()
                if text and text not in items:
                    items.append(text)
            elif isinstance(value, list):
                for entry in value:
                    text = str(entry or "").strip()
                    if text and text not in items:
                        items.append(text)
            elif isinstance(value, dict):
                for entry in value.values():
                    text = str(entry or "").strip()
                    if text and text not in items:
                        items.append(text)
        return items[:10]

    @staticmethod
    def _first_text(*values: Any) -> Optional[str]:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _normalize_required_text(value: Any, field_name: str, *, max_length: Optional[int] = None) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field_name} is required")
        if max_length is not None and len(text) > max_length:
            raise ValueError(f"{field_name} exceeds max length {max_length}")
        return text

    @staticmethod
    def _normalize_optional_text(value: Any, *, max_length: Optional[int] = None) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if max_length is not None and len(text) > max_length:
            raise ValueError(f"text exceeds max length {max_length}")
        return text or None

    @staticmethod
    def _normalize_market(value: Any) -> str:
        market = str(value or "").strip().lower()
        if market not in VALID_MARKETS:
            raise ValueError("market must be one of cn, hk, us, jp, kr, tw")
        return market

    @staticmethod
    def _normalize_entry_type(value: Any) -> str:
        entry_type = str(value or "").strip().lower()
        if entry_type not in JOURNAL_ENTRY_TYPES:
            allowed = ", ".join(sorted(JOURNAL_ENTRY_TYPES))
            raise ValueError(f"entry_type must be one of {allowed}")
        return entry_type

    @classmethod
    def _normalize_optional_entry_type(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        return cls._normalize_entry_type(value)

    @classmethod
    def _normalize_stock_code(cls, value: Any, *, market: Optional[str] = None) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("stock_code is required")
        market_norm = cls._normalize_market(market) if market else None
        code = DecisionSignalService.normalize_stock_code_for_signal(raw, market=market_norm)
        if not code:
            raise ValueError("stock_code is required")
        return code

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _normalize_processing_status(value: Any) -> str:
        status = InvestmentJournalRepository.normalize_processing_status(value)
        if status not in {"not_applicable", "pending", "processing", "completed", "failed"}:
            raise ValueError(f"unsupported ai_processing_status: {value}")
        return status
