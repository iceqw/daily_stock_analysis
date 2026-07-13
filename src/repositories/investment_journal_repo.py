# -*- coding: utf-8 -*-
"""Repository helpers for stock investment journal entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Tuple

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.exc import IntegrityError

from src.storage import DatabaseManager, InvestmentJournalEntry, utc_naive_now


@dataclass
class InvestmentJournalCreateResult:
    """Outcome of an idempotent journal entry create attempt."""

    row: InvestmentJournalEntry
    created: bool
    duplicate: bool = False


class InvestmentJournalMutationConflictError(RuntimeError):
    """Raised when a journal mutation targets the wrong entry type."""


class InvestmentJournalStateTransitionError(RuntimeError):
    """Raised when a journal structuring state transition is invalid."""


class InvestmentJournalRepository:
    """Persistence layer for investment_journal_entries."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create(self, fields: dict) -> InvestmentJournalEntry:
        with self.db.get_session() as session:
            row = InvestmentJournalEntry(**fields)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def create_analysis_entry_if_absent(self, fields: dict) -> InvestmentJournalCreateResult:
        source_analysis_history_id = int(fields["source_analysis_history_id"])

        def write_operation(session):
            existing = session.execute(
                select(InvestmentJournalEntry).where(
                    InvestmentJournalEntry.source_analysis_history_id == source_analysis_history_id
                )
            ).scalar_one_or_none()
            if existing is not None:
                session.expunge(existing)
                return InvestmentJournalCreateResult(row=existing, created=False, duplicate=True)
            row = InvestmentJournalEntry(**fields)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return InvestmentJournalCreateResult(row=row, created=True)

        try:
            return self.db._run_write_transaction(
                f"create_investment_journal_analysis_entry[{source_analysis_history_id}]",
                write_operation,
            )
        except IntegrityError:
            existing = self.get_by_source_analysis_history_id(source_analysis_history_id)
            if existing is None:
                raise
            return InvestmentJournalCreateResult(row=existing, created=False, duplicate=True)

    def get_by_source_analysis_history_id(
        self,
        source_analysis_history_id: int,
    ) -> Optional[InvestmentJournalEntry]:
        with self.db.get_session() as session:
            return session.execute(
                select(InvestmentJournalEntry).where(
                    InvestmentJournalEntry.source_analysis_history_id == int(source_analysis_history_id)
                ).limit(1)
            ).scalar_one_or_none()

    def get(self, entry_id: int) -> Optional[InvestmentJournalEntry]:
        with self.db.get_session() as session:
            return session.execute(
                select(InvestmentJournalEntry).where(InvestmentJournalEntry.id == int(entry_id)).limit(1)
            ).scalar_one_or_none()

    def update_manual_entry(
        self,
        entry_id: int,
        *,
        raw_content: Optional[str] = None,
        summary_snapshot: Optional[str] = None,
    ) -> Optional[InvestmentJournalEntry]:
        with self.db.get_session() as session:
            row = session.execute(
                select(InvestmentJournalEntry).where(InvestmentJournalEntry.id == int(entry_id)).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.entry_type != "manual":
                raise InvestmentJournalMutationConflictError("only manual journal entries can be updated")
            if raw_content is not None:
                row.raw_content = raw_content
                self._reset_structuring_fields(row, next_status="pending")
            if summary_snapshot is not None:
                row.summary_snapshot = summary_snapshot
            row.updated_at = utc_naive_now()
            session.commit()
            session.refresh(row)
            return row

    def reset_structuring(self, entry_id: int) -> Optional[InvestmentJournalEntry]:
        with self.db.get_session() as session:
            row = session.execute(
                select(InvestmentJournalEntry).where(InvestmentJournalEntry.id == int(entry_id)).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.entry_type != "manual":
                raise InvestmentJournalMutationConflictError("only manual journal entries can be structured")
            self._reset_structuring_fields(row, next_status="pending")
            row.updated_at = utc_naive_now()
            session.commit()
            session.refresh(row)
            return row

    def mark_processing(self, entry_id: int, *, attempt: int) -> Optional[InvestmentJournalEntry]:
        def write_operation(session):
            row = session.execute(
                select(InvestmentJournalEntry).where(InvestmentJournalEntry.id == int(entry_id)).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.entry_type != "manual":
                raise InvestmentJournalMutationConflictError("only manual journal entries can be structured")
            current_status = self.normalize_processing_status(row.ai_processing_status)
            if current_status != "pending" or int(row.structuring_attempt or 0) != int(attempt):
                raise InvestmentJournalStateTransitionError(
                    f"journal_status_not_pending:{current_status}"
                )
            row.ai_processing_status = "processing"
            row.structured_error = None
            row.updated_at = utc_naive_now()
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

        return self.db._run_write_transaction(
            f"mark_journal_processing[{int(entry_id)}]",
            write_operation,
        )

    def mark_completed(
        self,
        entry_id: int,
        *,
        structured_output_json: str,
        model: Optional[str],
        provider: Optional[str],
        temperature: Optional[float],
        prompt_version: Optional[str],
        structured_version: Optional[str],
        structured_at,
        attempt: int,
    ) -> Optional[InvestmentJournalEntry]:
        def write_operation(session):
            row = session.execute(
                select(InvestmentJournalEntry).where(InvestmentJournalEntry.id == int(entry_id)).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            current_status = self.normalize_processing_status(row.ai_processing_status)
            if current_status != "processing" or int(row.structuring_attempt or 0) != int(attempt):
                raise InvestmentJournalStateTransitionError(
                    f"journal_status_not_processing:{current_status}"
                )
            row.structured_output_json = structured_output_json
            row.ai_processing_status = "completed"
            row.model = model
            row.provider = provider
            row.temperature = temperature
            row.prompt_version = prompt_version
            row.structured_version = structured_version
            row.structured_at = structured_at
            row.structured_error = None
            row.updated_at = utc_naive_now()
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

        return self.db._run_write_transaction(
            f"mark_journal_completed[{int(entry_id)}]",
            write_operation,
        )

    def mark_failed(self, entry_id: int, *, error_message: str, attempt: Optional[int] = None) -> Optional[InvestmentJournalEntry]:
        def write_operation(session):
            row = session.execute(
                select(InvestmentJournalEntry).where(InvestmentJournalEntry.id == int(entry_id)).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            current_status = self.normalize_processing_status(row.ai_processing_status)
            if attempt is not None and int(row.structuring_attempt or 0) != int(attempt):
                raise InvestmentJournalStateTransitionError("journal_attempt_superseded")
            if current_status not in {"pending", "processing"}:
                raise InvestmentJournalStateTransitionError(
                    f"journal_status_not_mutable:{current_status}"
                )
            row.ai_processing_status = "failed"
            row.structured_error = str(error_message or "").strip()[:500] or "structuring_failed"
            row.updated_at = utc_naive_now()
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

        return self.db._run_write_transaction(
            f"mark_journal_failed[{int(entry_id)}]",
            write_operation,
        )

    def fail_stale_structuring(self, *, timeout_seconds: int) -> int:
        cutoff = utc_naive_now() - timedelta(seconds=max(1, int(timeout_seconds)))
        with self.db.get_session() as session:
            rows = session.execute(
                select(InvestmentJournalEntry).where(
                    InvestmentJournalEntry.entry_type == "manual",
                    InvestmentJournalEntry.ai_processing_status.in_(("pending", "processing")),
                    InvestmentJournalEntry.structuring_requested_at.is_not(None),
                    InvestmentJournalEntry.structuring_requested_at <= cutoff,
                )
            ).scalars().all()
            for row in rows:
                row.ai_processing_status = "failed"
                row.structured_error = "structuring_timeout"
                row.updated_at = utc_naive_now()
            session.commit()
            return len(rows)

    def list_by_stock(
        self,
        *,
        stock_code: str,
        market: str,
        entry_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Tuple[List[InvestmentJournalEntry], int]:
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        offset = (safe_page - 1) * safe_page_size
        conditions = [
            InvestmentJournalEntry.stock_code == stock_code,
            InvestmentJournalEntry.market == market,
        ]
        if entry_type:
            conditions.append(InvestmentJournalEntry.entry_type == entry_type)
        if search:
            term = f"%{search.strip()}%"
            conditions.append(or_(
                InvestmentJournalEntry.raw_content.ilike(term),
                InvestmentJournalEntry.summary_snapshot.ilike(term),
                InvestmentJournalEntry.risk_summary.ilike(term),
                InvestmentJournalEntry.source_label.ilike(term),
            ))
        order_column = {
            "created_at": InvestmentJournalEntry.created_at,
            "updated_at": InvestmentJournalEntry.updated_at,
            "status": InvestmentJournalEntry.ai_processing_status,
            "type": InvestmentJournalEntry.entry_type,
        }.get(sort_by, InvestmentJournalEntry.created_at)
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(InvestmentJournalEntry.id)).where(*conditions)
            ).scalar() or 0
            rows = session.execute(
                select(InvestmentJournalEntry)
                .where(*conditions)
                .order_by((asc if str(sort_order).lower() == "asc" else desc)(order_column), desc(InvestmentJournalEntry.id))
                .offset(offset)
                .limit(safe_page_size)
            ).scalars().all()
            return list(rows), int(total)

    def stock_stats(self, *, stock_code: str, market: str) -> dict:
        with self.db.get_session() as session:
            rows = session.execute(select(InvestmentJournalEntry).where(
                InvestmentJournalEntry.stock_code == stock_code,
                InvestmentJournalEntry.market == market,
            )).scalars().all()
        stats = {"total": len(rows), "analysis": 0, "manual": 0, "completed": 0, "pending": 0, "processing": 0, "failed": 0, "source_deleted": 0}
        for row in rows:
            if row.entry_type in stats:
                stats[row.entry_type] += 1
            status = self.normalize_processing_status(row.ai_processing_status)
            if status in stats:
                stats[status] += 1
            if row.source_status == "deleted":
                stats["source_deleted"] += 1
        return stats

    @staticmethod
    def normalize_processing_status(value: Optional[str]) -> str:
        status = str(value or "").strip().lower()
        if status == "succeeded":
            return "completed"
        return status or "pending"

    @classmethod
    def _reset_structuring_fields(cls, row: InvestmentJournalEntry, *, next_status: str) -> None:
        row.structured_output_json = None
        row.ai_processing_status = cls.normalize_processing_status(next_status)
        row.model = None
        row.provider = None
        row.temperature = None
        row.prompt_version = None
        row.structured_version = None
        row.structured_at = None
        row.structured_error = None
        row.structuring_attempt = int(row.structuring_attempt or 0) + 1
        row.structuring_requested_at = utc_naive_now()
