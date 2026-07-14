# -*- coding: utf-8 -*-
"""Business rules for the investment principle foundation layer."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.exc import IntegrityError

from src.repositories.ai_opinion_repo import AIOpinionRepository
from src.repositories.investment_journal_repo import InvestmentJournalRepository
from src.repositories.investment_principle_repo import (
    InvestmentPrincipleConcurrencyError as RepositoryConcurrencyError,
    InvestmentPrincipleDetail,
    InvestmentPrincipleNotFoundError as RepositoryNotFoundError,
    InvestmentPrincipleRepository,
    InvestmentPrincipleRepositoryError,
)
from src.services.decision_signal_service import DecisionSignalService
from src.services.portfolio_service import VALID_MARKETS
from src.storage import DatabaseManager, utc_naive_now


PRINCIPLE_STATUSES = frozenset({"draft", "active", "archived", "rejected"})
PRINCIPLE_SEVERITIES = frozenset({"hard", "soft", "advisory"})
PRINCIPLE_SCOPE_TYPES = frozenset({"global", "market", "stock"})
PRINCIPLE_SOURCE_TYPES = frozenset({"manual", "journal", "opinion"})
PRINCIPLE_SOURCE_STATUSES = frozenset({"available", "deleted", "unavailable"})
PRINCIPLE_SORT_FIELDS = frozenset({"updated_at", "created_at", "title", "status"})
PRINCIPLE_VERSION_FIELDS = (
    "title",
    "statement",
    "rationale",
    "category",
    "severity",
    "scope_type",
    "scope_market",
    "scope_stock_code",
)
MAX_TITLE_LENGTH = 200
MAX_LONG_TEXT_LENGTH = 20_000
MAX_SOURCE_EXCERPT_LENGTH = 4_000


class InvestmentPrincipleServiceError(Exception):
    """Base service error."""


class InvestmentPrincipleValidationError(InvestmentPrincipleServiceError):
    """Raised when input or a requested business operation is invalid."""


class InvestmentPrincipleNotFoundError(InvestmentPrincipleServiceError):
    """Raised when a principle or referenced source does not exist."""


class InvestmentPrincipleConflictError(InvestmentPrincipleServiceError):
    """Raised for invalid state transitions or stale optimistic writes."""


class InvestmentPrincipleDataIntegrityError(InvestmentPrincipleServiceError):
    """Raised when persisted principle data is internally inconsistent."""


class InvestmentPrincipleService:
    """Validate and orchestrate investment principle operations."""

    _ALLOWED_TRANSITIONS = {
        "draft": {"active", "rejected"},
        "active": {"archived"},
        "archived": {"active"},
        "rejected": {"draft"},
    }
    _SOURCE_TRANSITIONS = {
        "available": {"deleted", "unavailable"},
        "unavailable": {"available", "deleted"},
        "deleted": set(),
    }

    def __init__(
        self,
        repo: Optional[InvestmentPrincipleRepository] = None,
        db_manager: Optional[DatabaseManager] = None,
        journal_repo: Optional[InvestmentJournalRepository] = None,
        opinion_repo: Optional[AIOpinionRepository] = None,
    ):
        self.repo = repo or InvestmentPrincipleRepository(db_manager)
        self.db = db_manager or getattr(self.repo, "db", None) or DatabaseManager.get_instance()
        self.journal_repo = journal_repo or InvestmentJournalRepository(self.db)
        self.opinion_repo = opinion_repo or AIOpinionRepository(self.db)

    def create_principle(
        self,
        *,
        title: Any,
        statement: Any,
        rationale: Any = None,
        category: Any,
        severity: Any = "advisory",
        scope_type: Any = "global",
        scope_market: Any = None,
        scope_stock_code: Any = None,
        change_note: Any = None,
        status: Any = None,
        sources: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> InvestmentPrincipleDetail:
        if status not in (None, "") and self._normalize_enum(status, PRINCIPLE_STATUSES, "status") != "draft":
            raise InvestmentPrincipleValidationError("new principles must start in draft status")
        fields = self._normalize_version_fields(
            {
                "title": title,
                "statement": statement,
                "rationale": rationale,
                "category": category,
                "severity": severity,
                "scope_type": scope_type,
                "scope_market": scope_market,
                "scope_stock_code": scope_stock_code,
                "change_note": change_note,
            }
        )
        normalized_sources = self._normalize_sources(sources or [])
        self._ensure_no_duplicate_sources(normalized_sources)
        try:
            return self.repo.create_principle_with_initial_version(
                fields,
                sources=normalized_sources,
            )
        except RepositoryNotFoundError as exc:
            raise InvestmentPrincipleNotFoundError(str(exc)) from exc
        except RepositoryConcurrencyError as exc:
            raise InvestmentPrincipleConflictError(str(exc)) from exc
        except IntegrityError as exc:
            raise InvestmentPrincipleDataIntegrityError("investment principle creation failed") from exc
        except InvestmentPrincipleRepositoryError as exc:
            raise InvestmentPrincipleDataIntegrityError(str(exc)) from exc

    def get_principle(self, principle_id: Any) -> InvestmentPrincipleDetail:
        normalized_id = self._normalize_positive_id(principle_id, "principle_id")
        try:
            detail = self.repo.get_principle_detail(normalized_id)
        except RepositoryNotFoundError as exc:
            raise InvestmentPrincipleNotFoundError(str(exc)) from exc
        except InvestmentPrincipleRepositoryError as exc:
            raise InvestmentPrincipleDataIntegrityError(str(exc)) from exc
        if detail is None:
            raise InvestmentPrincipleNotFoundError(f"investment principle not found: {normalized_id}")
        return detail

    def list_principles(
        self,
        *,
        status: Any = None,
        category: Any = None,
        severity: Any = None,
        scope_type: Any = None,
        market: Any = None,
        stock_code: Any = None,
        keyword: Any = None,
        page: Any = 1,
        page_size: Any = 20,
        sort_by: Any = "updated_at",
        sort_order: Any = "desc",
    ):
        normalized_page, normalized_page_size = self._normalize_pagination(page, page_size)
        normalized_status = self._normalize_optional_enum(status, PRINCIPLE_STATUSES, "status")
        normalized_category = self._normalize_optional_text(category, "category", 64)
        normalized_severity = self._normalize_optional_enum(severity, PRINCIPLE_SEVERITIES, "severity")
        normalized_scope = self._normalize_optional_enum(scope_type, PRINCIPLE_SCOPE_TYPES, "scope_type")
        normalized_market = self._normalize_optional_market(market)
        normalized_code = None
        if stock_code not in (None, ""):
            if normalized_market is None:
                raise InvestmentPrincipleValidationError("market is required when stock_code is provided")
            normalized_code = self._normalize_stock_code(stock_code, normalized_market)
        normalized_keyword = self._normalize_optional_text(keyword, "keyword", 120)
        normalized_sort = self._normalize_enum(sort_by, PRINCIPLE_SORT_FIELDS, "sort_by")
        normalized_order = self._normalize_enum(sort_order, {"asc", "desc"}, "sort_order")
        return self.repo.list_current(
            status=normalized_status,
            category=normalized_category,
            severity=normalized_severity,
            scope_type=normalized_scope,
            scope_market=normalized_market,
            scope_stock_code=normalized_code,
            keyword=normalized_keyword,
            page=normalized_page,
            page_size=normalized_page_size,
            sort_by=normalized_sort,
            sort_order=normalized_order,
        )

    def list_versions(self, principle_id: Any, *, page: Any = 1, page_size: Any = 20):
        normalized_id = self._normalize_positive_id(principle_id, "principle_id")
        normalized_page, normalized_page_size = self._normalize_pagination(page, page_size)
        try:
            return self.repo.list_versions(normalized_id, normalized_page, normalized_page_size)
        except RepositoryNotFoundError as exc:
            raise InvestmentPrincipleNotFoundError(str(exc)) from exc

    def list_version_sources(self, principle_version_id: Any):
        version_id = self._normalize_positive_id(principle_version_id, "principle_version_id")
        return self.repo.list_sources_for_version(version_id)

    def update_principle(
        self,
        principle_id: Any,
        *,
        expected_current_version: Any,
        fields: Dict[str, Any],
        sources: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> InvestmentPrincipleDetail:
        normalized_id = self._normalize_positive_id(principle_id, "principle_id")
        expected_version = self._normalize_positive_id(expected_current_version, "expected_current_version")
        detail = self.get_principle(normalized_id)
        if detail.principle.status == "rejected":
            raise InvestmentPrincipleConflictError("rejected principles must be restored before editing")

        normalized_sources = self._normalize_sources(sources or [])
        self._ensure_no_duplicate_sources(normalized_sources, principle_id=normalized_id)
        merged = self._merge_version_fields(detail, fields)
        changed = any(merged[key] != getattr(detail.version, key) for key in PRINCIPLE_VERSION_FIELDS)
        if not changed and not normalized_sources:
            raise InvestmentPrincipleValidationError("no_effective_changes")
        if not changed:
            try:
                self.repo.add_sources_to_version(detail.version.id, normalized_sources)
                return self.get_principle(normalized_id)
            except RepositoryNotFoundError as exc:
                raise InvestmentPrincipleNotFoundError(str(exc)) from exc
            except IntegrityError as exc:
                raise InvestmentPrincipleDataIntegrityError("source append failed") from exc

        try:
            return self.repo.create_next_version(
                normalized_id,
                expected_version,
                {**merged, "change_note": self._normalize_change_note(fields.get("change_note"))},
                sources=normalized_sources,
            )
        except RepositoryNotFoundError as exc:
            raise InvestmentPrincipleNotFoundError(str(exc)) from exc
        except RepositoryConcurrencyError as exc:
            raise InvestmentPrincipleConflictError(str(exc)) from exc
        except IntegrityError as exc:
            raise InvestmentPrincipleDataIntegrityError("investment principle update failed") from exc

    def activate_principle(self, principle_id: Any, *, expected_status: Any = None) -> InvestmentPrincipleDetail:
        return self._transition(principle_id, "active", expected_status=expected_status, activated_at=utc_naive_now())

    def archive_principle(self, principle_id: Any, *, expected_status: Any = None) -> InvestmentPrincipleDetail:
        return self._transition(principle_id, "archived", expected_status=expected_status, archived_at=utc_naive_now())

    def reject_principle(self, principle_id: Any, *, expected_status: Any = None) -> InvestmentPrincipleDetail:
        return self._transition(principle_id, "rejected", expected_status=expected_status, rejected_at=utc_naive_now())

    def restore_principle_to_draft(self, principle_id: Any, *, expected_status: Any = None) -> InvestmentPrincipleDetail:
        return self._transition(principle_id, "draft", expected_status=expected_status)

    def mark_source_status(self, source_id: Any, new_status: Any):
        normalized_id = self._normalize_positive_id(source_id, "source_id")
        normalized_status = self._normalize_enum(new_status, PRINCIPLE_SOURCE_STATUSES, "source_status")
        sources = self._find_source(normalized_id)
        if sources is None:
            raise InvestmentPrincipleNotFoundError(f"investment principle source not found: {normalized_id}")
        current_status = str(sources.source_status or "").strip().lower()
        if normalized_status == current_status or normalized_status not in self._SOURCE_TRANSITIONS.get(current_status, set()):
            raise InvestmentPrincipleConflictError(
                f"invalid source status transition: {current_status}->{normalized_status}"
            )
        try:
            return self.repo.update_source_status(normalized_id, normalized_status, utc_naive_now())
        except IntegrityError as exc:
            raise InvestmentPrincipleDataIntegrityError("source status update failed") from exc

    def _transition(self, principle_id: Any, new_status: str, *, expected_status: Any = None, **timestamps) -> InvestmentPrincipleDetail:
        normalized_id = self._normalize_positive_id(principle_id, "principle_id")
        detail = self.get_principle(normalized_id)
        current_status = detail.principle.status
        if expected_status is not None:
            expected = self._normalize_enum(expected_status, PRINCIPLE_STATUSES, "expected_status")
            if expected != current_status:
                raise InvestmentPrincipleConflictError(
                    f"stale expected status: expected={expected}, actual={current_status}"
                )
        if new_status not in self._ALLOWED_TRANSITIONS.get(current_status, set()):
            raise InvestmentPrincipleConflictError(
                f"invalid principle status transition: {current_status}->{new_status}"
            )
        now = utc_naive_now()
        try:
            updated = self.repo.update_principle_status(
                normalized_id,
                expected_status=current_status,
                new_status=new_status,
                status_changed_at=now,
                **timestamps,
            )
        except RepositoryConcurrencyError as exc:
            raise InvestmentPrincipleConflictError(str(exc)) from exc
        if updated is None:
            raise InvestmentPrincipleNotFoundError(f"investment principle not found: {normalized_id}")
        return self.get_principle(normalized_id)

    def _merge_version_fields(self, detail: InvestmentPrincipleDetail, fields: Dict[str, Any]) -> Dict[str, Any]:
        values = {key: getattr(detail.version, key) for key in PRINCIPLE_VERSION_FIELDS}
        provided = {key: value for key, value in fields.items() if key in PRINCIPLE_VERSION_FIELDS or key == "change_note"}
        if not provided:
            return values
        normalized = self._normalize_version_fields({**values, **provided})
        return {key: normalized[key] for key in PRINCIPLE_VERSION_FIELDS}

    def _normalize_version_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        title = self._normalize_required_text(fields.get("title"), "title", MAX_TITLE_LENGTH)
        statement = self._normalize_required_text(fields.get("statement"), "statement", MAX_LONG_TEXT_LENGTH)
        category = self._normalize_required_text(fields.get("category"), "category", 64)
        severity = self._normalize_enum(fields.get("severity"), PRINCIPLE_SEVERITIES, "severity")
        scope_type = self._normalize_enum(fields.get("scope_type"), PRINCIPLE_SCOPE_TYPES, "scope_type")
        market = self._normalize_optional_market(fields.get("scope_market"))
        stock_code = fields.get("scope_stock_code")
        if scope_type == "global":
            if market is not None or stock_code not in (None, ""):
                raise InvestmentPrincipleValidationError("global scope cannot include market or stock_code")
            market = None
            stock_code = None
        elif scope_type == "market":
            if market is None:
                raise InvestmentPrincipleValidationError("market scope requires scope_market")
            if stock_code not in (None, ""):
                raise InvestmentPrincipleValidationError("market scope cannot include scope_stock_code")
            stock_code = None
        else:
            if market is None:
                raise InvestmentPrincipleValidationError("stock scope requires scope_market")
            stock_code = self._normalize_stock_code(stock_code, market)
        return {
            "title": title,
            "statement": statement,
            "rationale": self._normalize_optional_text(fields.get("rationale"), "rationale", MAX_LONG_TEXT_LENGTH),
            "category": category,
            "severity": severity,
            "scope_type": scope_type,
            "scope_market": market,
            "scope_stock_code": stock_code,
            "change_note": self._normalize_change_note(fields.get("change_note")),
        }

    def _normalize_sources(self, sources: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = []
        seen = set()
        for source in sources:
            if not isinstance(source, dict):
                raise InvestmentPrincipleValidationError("source must be an object")
            source_type = self._normalize_enum(source.get("source_type"), PRINCIPLE_SOURCE_TYPES, "source_type")
            supplied_status = source.get("source_status")
            if supplied_status not in (None, "", "available"):
                raise InvestmentPrincipleValidationError("new source_status must be available")
            if source_type == "manual":
                if source.get("source_id") not in (None, ""):
                    raise InvestmentPrincipleValidationError("manual source cannot include source_id")
                excerpt = self._normalize_required_text(
                    source.get("source_excerpt"), "source_excerpt", MAX_SOURCE_EXCERPT_LENGTH
                )
                dedup_key = (source_type, excerpt)
                source_id = None
            else:
                source_id = self._normalize_positive_id(source.get("source_id"), "source_id")
                excerpt = self._build_source_excerpt(source_type, source_id)
                dedup_key = (source_type, str(source_id))
            if dedup_key in seen:
                raise InvestmentPrincipleValidationError("duplicate source in request")
            seen.add(dedup_key)
            normalized.append({
                "source_type": source_type,
                "source_id": None if source_id is None else str(source_id),
                "source_excerpt": excerpt,
                "source_status": "available",
            })
        return normalized

    def _build_source_excerpt(self, source_type: str, source_id: int) -> str:
        if source_type == "journal":
            row = self.journal_repo.get(source_id)
            if row is None:
                raise InvestmentPrincipleNotFoundError(f"investment journal not found: {source_id}")
            candidates = (row.raw_content, row.summary_snapshot, row.risk_summary)
        else:
            row = self.opinion_repo.get(source_id)
            if row is None:
                raise InvestmentPrincipleNotFoundError(f"AI opinion not found: {source_id}")
            output = row.output_json or ""
            candidates = (row.title, row.content, row.conclusion, output)
        for candidate in candidates:
            text = str(candidate or "").strip()
            if text:
                return text[:MAX_SOURCE_EXCERPT_LENGTH]
        raise InvestmentPrincipleDataIntegrityError(f"{source_type} source has no snapshot content: {source_id}")

    def _ensure_no_duplicate_sources(self, sources: Sequence[Dict[str, Any]], principle_id: Optional[int] = None) -> None:
        keys = {(item["source_type"], item["source_id"] or item["source_excerpt"]) for item in sources}
        if len(keys) != len(sources):
            raise InvestmentPrincipleValidationError("duplicate source in request")
        if principle_id is None:
            return
        versions = self.repo.list_versions(principle_id, page=1, page_size=100)
        for version in versions.items:
            existing = self.repo.list_sources_for_version(version.id)
            existing_keys = {(row.source_type, row.source_id or str(row.source_excerpt or "").strip()) for row in existing}
            if keys & existing_keys:
                raise InvestmentPrincipleConflictError("source already attached to this principle")

    def _find_source(self, source_id: int):
        return self.repo.get_source_by_id(source_id)

    @staticmethod
    def _normalize_positive_id(value: Any, field_name: str) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            raise InvestmentPrincipleValidationError(f"{field_name} must be a positive integer") from None
        if normalized <= 0:
            raise InvestmentPrincipleValidationError(f"{field_name} must be a positive integer")
        return normalized

    @staticmethod
    def _normalize_required_text(value: Any, field_name: str, max_length: int) -> str:
        text = str(value or "").strip()
        if not text:
            raise InvestmentPrincipleValidationError(f"{field_name} is required")
        if len(text) > max_length:
            raise InvestmentPrincipleValidationError(f"{field_name} exceeds max length {max_length}")
        return text

    @staticmethod
    def _normalize_optional_text(value: Any, field_name: str, max_length: int) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if len(text) > max_length:
            raise InvestmentPrincipleValidationError(f"{field_name} exceeds max length {max_length}")
        return text or None

    @staticmethod
    def _normalize_change_note(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if len(text) > MAX_LONG_TEXT_LENGTH:
            raise InvestmentPrincipleValidationError("change_note exceeds max length 20000")
        return text or None

    @staticmethod
    def _normalize_enum(value: Any, allowed: Iterable[str], field_name: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in allowed:
            raise InvestmentPrincipleValidationError(f"{field_name} is invalid")
        return normalized

    @classmethod
    def _normalize_optional_enum(cls, value: Any, allowed: Iterable[str], field_name: str) -> Optional[str]:
        if value in (None, ""):
            return None
        return cls._normalize_enum(value, allowed, field_name)

    @staticmethod
    def _normalize_optional_market(value: Any) -> Optional[str]:
        if value in (None, ""):
            return None
        market = str(value).strip().lower()
        if market not in VALID_MARKETS:
            raise InvestmentPrincipleValidationError("market is invalid")
        return market

    @staticmethod
    def _normalize_stock_code(value: Any, market: str) -> str:
        if value in (None, ""):
            raise InvestmentPrincipleValidationError("scope_stock_code is required")
        try:
            return DecisionSignalService.normalize_stock_code_for_signal(value, market=market)
        except (TypeError, ValueError) as exc:
            raise InvestmentPrincipleValidationError("scope_stock_code is invalid") from exc

    @staticmethod
    def _normalize_pagination(page: Any, page_size: Any) -> tuple[int, int]:
        try:
            normalized_page = int(page)
            normalized_page_size = int(page_size)
        except (TypeError, ValueError):
            raise InvestmentPrincipleValidationError("page and page_size must be positive integers") from None
        if normalized_page < 1 or normalized_page_size < 1:
            raise InvestmentPrincipleValidationError("page and page_size must be positive integers")
        if normalized_page_size > 100:
            raise InvestmentPrincipleValidationError("page_size must be at most 100")
        return normalized_page, normalized_page_size
