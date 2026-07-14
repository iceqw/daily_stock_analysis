# -*- coding: utf-8 -*-
"""Build a deterministic, read-only context snapshot of active principles."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from src.repositories.investment_principle_repo import (
    InvestmentPrincipleCurrentVersionError,
    InvestmentPrincipleRepository,
    InvestmentPrincipleRepositoryError,
)
from src.storage import DatabaseManager


class PrincipleContextError(Exception):
    """Base error for principle context construction."""


class PrincipleContextReadError(PrincipleContextError):
    """Raised when the formal principle read cannot be completed."""


class PrincipleContextValidationError(PrincipleContextError):
    """Raised when persisted principles or analysis scope are invalid."""


@dataclass(frozen=True)
class PrincipleScope:
    """Immutable scope value carried by a snapshot item."""

    type: str
    market: Optional[str]
    stock_code: Optional[str]

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "type": self.type,
            "market": self.market,
            "stock_code": self.stock_code,
        }


@dataclass(frozen=True)
class PrincipleSnapshotItem:
    principle_id: int
    principle_version: int
    category: str
    severity: str
    scope: PrincipleScope
    title: str
    statement: str
    rationale: str
    content_hash: str
    text_truncated: bool = field(default=False, repr=False, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        """Return fields in the fixed snapshot order."""
        return {
            "principle_id": self.principle_id,
            "principle_version": self.principle_version,
            "category": self.category,
            "severity": self.severity,
            "scope": self.scope.to_dict(),
            "title": self.title,
            "statement": self.statement,
            "rationale": self.rationale,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class PrincipleContextSnapshot:
    items: tuple[PrincipleSnapshotItem, ...]
    snapshot_json: str
    snapshot_hash: str
    source_count: int
    retained_count: int
    truncated_count: int
    truncated: bool
    builder_version: str
    normalization_version: str
    sort_version: str
    estimated_size: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "snapshot_json": self.snapshot_json,
            "snapshot_hash": self.snapshot_hash,
            "source_count": self.source_count,
            "retained_count": self.retained_count,
            "truncated_count": self.truncated_count,
            "truncated": self.truncated,
            "builder_version": self.builder_version,
            "normalization_version": self.normalization_version,
            "sort_version": self.sort_version,
            "estimated_size": self.estimated_size,
        }


class PrincipleContextBuilder:
    """Read active/current principles and construct a deterministic snapshot.

    The builder has no write path and never invokes an LLM. Scope support is
    intentionally limited to the fields that exist in M-1: market and stock
    code, plus the global scope.
    """

    BUILDER_VERSION = "principle-context-builder-v1"
    NORMALIZATION_VERSION = "principle-normalization-v1"
    SORT_VERSION = "principle-sort-v1"

    MAX_PRINCIPLES = 20
    MAX_STATEMENT_CHARS = 2_000
    MAX_RATIONALE_CHARS = 2_000
    MAX_TOTAL_CHARS = 12_000
    SEVERITY_RANK = {"hard": 0, "soft": 1, "advisory": 2}

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        *,
        repository: Optional[InvestmentPrincipleRepository] = None,
        max_principles: int = MAX_PRINCIPLES,
        max_statement_chars: int = MAX_STATEMENT_CHARS,
        max_rationale_chars: int = MAX_RATIONALE_CHARS,
        max_total_chars: int = MAX_TOTAL_CHARS,
    ) -> None:
        self.repository = repository or InvestmentPrincipleRepository(db_manager)
        self.max_principles = self._positive_limit(max_principles, "max_principles")
        self.max_statement_chars = self._positive_limit(max_statement_chars, "max_statement_chars")
        self.max_rationale_chars = self._positive_limit(max_rationale_chars, "max_rationale_chars")
        self.max_total_chars = self._positive_limit(max_total_chars, "max_total_chars")

    def build(
        self,
        context: Optional[Mapping[str, Any]] = None,
        *,
        market: Optional[str] = None,
        stock_code: Optional[str] = None,
    ) -> PrincipleContextSnapshot:
        """Build a snapshot for an analysis scope without mutating storage."""
        scope = self._analysis_scope(context, market=market, stock_code=stock_code)
        try:
            rows = self.repository.list_active_current()
        except InvestmentPrincipleCurrentVersionError as exc:
            raise PrincipleContextValidationError(str(exc)) from exc
        except InvestmentPrincipleRepositoryError as exc:
            raise PrincipleContextReadError(str(exc)) from exc
        except Exception as exc:
            raise PrincipleContextReadError("investment principle read failed") from exc

        normalized: List[PrincipleSnapshotItem] = []
        seen_ids = set()
        for row in rows:
            item = self._normalize_row(row)
            if item.principle_id in seen_ids:
                raise PrincipleContextValidationError(
                    f"duplicate active principle identity: {item.principle_id}"
                )
            seen_ids.add(item.principle_id)
            if self._scope_matches(item.scope, scope):
                normalized.append(item)

        normalized.sort(key=self._sort_key)
        retained: List[PrincipleSnapshotItem] = []
        truncated_count = 0
        text_truncated = False
        used_chars = 0
        for index, item in enumerate(normalized):
            if len(retained) >= self.max_principles:
                truncated_count = len(normalized) - index
                break
            item_size = len(item.title) + len(item.statement) + len(item.rationale)
            if used_chars + item_size > self.max_total_chars:
                truncated_count = len(normalized) - index
                break
            retained.append(item)
            used_chars += item_size
            if item.text_truncated:
                text_truncated = True

        retained_items = tuple(retained)
        payload = [item.to_dict() for item in retained_items]
        snapshot_json = self._canonical_json(payload)
        snapshot_hash = self._sha256(snapshot_json)
        return PrincipleContextSnapshot(
            items=retained_items,
            snapshot_json=snapshot_json,
            snapshot_hash=snapshot_hash,
            source_count=len(rows),
            retained_count=len(retained_items),
            truncated_count=truncated_count,
            truncated=bool(text_truncated or truncated_count),
            builder_version=self.BUILDER_VERSION,
            normalization_version=self.NORMALIZATION_VERSION,
            sort_version=self.SORT_VERSION,
            estimated_size=len(snapshot_json),
        )

    def _normalize_row(self, row: Any) -> PrincipleSnapshotItem:
        principle = getattr(row, "principle", None)
        version = getattr(row, "version", None)
        if principle is None or version is None:
            raise PrincipleContextValidationError("active principle row is incomplete")
        if self._normalize_text(getattr(principle, "status", None)).lower() != "active":
            raise PrincipleContextValidationError("context row is not active")

        principle_id = self._positive_int(getattr(principle, "id", None), "principle_id")
        principle_version = self._positive_int(getattr(version, "version", None), "principle_version")
        current_version = self._positive_int(
            getattr(principle, "current_version", None), "current_version"
        )
        if principle_id != self._positive_int(getattr(version, "principle_id", None), "principle_id"):
            raise PrincipleContextValidationError("principle/version identity mismatch")
        if principle_version != current_version:
            raise PrincipleContextValidationError(
                f"current_version_mismatch:{principle_id}:{current_version}:{principle_version}"
            )

        scope_type = self._normalize_text(getattr(version, "scope_type", None)).lower()
        if scope_type not in {"global", "market", "stock"}:
            raise PrincipleContextValidationError(f"scope_type is invalid: {scope_type}")
        scope_market = self._normalize_text(getattr(version, "scope_market", None)).lower() or None
        scope_stock_code = self._normalize_text(getattr(version, "scope_stock_code", None)).upper() or None
        if scope_type == "global":
            scope_market = None
            scope_stock_code = None
        elif scope_type == "market" and not scope_market:
            raise PrincipleContextValidationError("market scope requires scope_market")
        elif scope_type == "stock" and (not scope_market or not scope_stock_code):
            raise PrincipleContextValidationError("stock scope requires market and stock code")

        raw_statement = self._normalize_text(getattr(version, "statement", None))
        statement = self._truncate(raw_statement, self.max_statement_chars)
        title = self._normalize_text(getattr(version, "title", None))
        category = self._normalize_text(getattr(version, "category", None))
        severity = self._normalize_text(getattr(version, "severity", None)).lower()
        if not title or not statement or not category or not severity:
            raise PrincipleContextValidationError("principle snapshot contains missing required text")
        raw_rationale = self._normalize_text(getattr(version, "rationale", None))
        rationale = self._truncate(raw_rationale, self.max_rationale_chars)
        payload = {
            "principle_id": principle_id,
            "principle_version": principle_version,
            "category": category,
            "severity": severity,
            "scope": PrincipleScope(scope_type, scope_market, scope_stock_code),
            "title": title,
            "statement": statement,
            "rationale": rationale,
        }
        hash_payload = dict(payload)
        hash_payload["scope"] = payload["scope"].to_dict()
        content_hash = self._sha256(self._canonical_json(hash_payload))
        return PrincipleSnapshotItem(
            content_hash=content_hash,
            text_truncated=(len(raw_statement) > len(statement) or len(raw_rationale) > len(rationale)),
            **payload,
        )

    @staticmethod
    def _analysis_scope(
        context: Optional[Mapping[str, Any]],
        *,
        market: Optional[str],
        stock_code: Optional[str],
    ) -> Dict[str, Optional[str]]:
        values: Dict[str, Any] = dict(context or {})
        if market is not None:
            values["market"] = market
        if stock_code is not None:
            values["stock_code"] = stock_code
        return {
            "market": PrincipleContextBuilder._normalize_text(values.get("market")).lower() or None,
            "stock_code": PrincipleContextBuilder._normalize_text(values.get("stock_code")).upper() or None,
        }

    @staticmethod
    def _scope_matches(scope: PrincipleScope, analysis: Mapping[str, Optional[str]]) -> bool:
        if scope.type == "global":
            return True
        if not analysis.get("market") or scope.market != analysis.get("market"):
            return False
        if scope.type == "market":
            return True
        return bool(analysis.get("stock_code") and scope.stock_code == analysis.get("stock_code"))

    @classmethod
    def _sort_key(cls, item: PrincipleSnapshotItem) -> tuple[Any, ...]:
        return (
            cls.SEVERITY_RANK.get(item.severity, len(cls.SEVERITY_RANK)),
            item.severity,
            item.category,
            item.principle_id,
            item.principle_version,
        )

    @staticmethod
    def _normalize_text(value: Any) -> str:
        text = "" if value is None else str(value)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        return unicodedata.normalize("NFC", text).strip()

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        return text[:limit]

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _positive_int(value: Any, field_name: str) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            raise PrincipleContextValidationError(f"{field_name} must be a positive integer") from None
        if normalized <= 0:
            raise PrincipleContextValidationError(f"{field_name} must be a positive integer")
        return normalized

    @staticmethod
    def _positive_limit(value: Any, field_name: str) -> int:
        return PrincipleContextBuilder._positive_int(value, field_name)
