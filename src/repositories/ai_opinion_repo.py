# -*- coding: utf-8 -*-
"""Repository helpers for versioned AI opinion records."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError

from src.storage import AnalysisHistory, AIOpinionRecord, DatabaseManager, utc_naive_now


class AIOpinionVersionConflictError(RuntimeError):
    """Raised when a new AI opinion version conflicts with concurrent writes."""


class AIOpinionStateTransitionError(RuntimeError):
    """Raised when an AI opinion cannot move to the requested runtime state."""


class AIOpinionRepository:
    """Persistence layer for ai_opinions."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create_version(self, fields: dict) -> AIOpinionRecord:
        analysis_history_id = int(fields["analysis_history_id"])
        mark_as_current = bool(fields.pop("is_current", True))

        def write_operation(session):
            latest_version = session.execute(
                select(func.max(AIOpinionRecord.version)).where(
                    AIOpinionRecord.analysis_history_id == analysis_history_id
                )
            ).scalar()
            next_version = int(latest_version or 0) + 1
            now_value = utc_naive_now()
            if mark_as_current:
                for row in session.execute(
                    select(AIOpinionRecord).where(
                        AIOpinionRecord.analysis_history_id == analysis_history_id,
                        AIOpinionRecord.is_current.is_(True),
                    )
                ).scalars().all():
                    row.is_current = False
                    row.updated_at = now_value
            row = AIOpinionRecord(
                **fields,
                version=next_version,
                is_current=mark_as_current,
                created_at=fields.get("created_at") or now_value,
                updated_at=fields.get("updated_at") or now_value,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

        try:
            return self.db._run_write_transaction(
                f"create_ai_opinion_version[{analysis_history_id}]",
                write_operation,
            )
        except IntegrityError as exc:
            raise AIOpinionVersionConflictError(
                f"AI opinion version conflict for analysis_history_id={analysis_history_id}"
            ) from exc

    def get(self, opinion_id: int) -> Optional[AIOpinionRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(AIOpinionRecord).where(AIOpinionRecord.id == int(opinion_id)).limit(1)
            ).scalar_one_or_none()

    def has_inflight_generation(self, analysis_history_id: int) -> bool:
        with self.db.get_session() as session:
            count = session.execute(
                select(func.count(AIOpinionRecord.id)).where(
                    AIOpinionRecord.analysis_history_id == int(analysis_history_id),
                    AIOpinionRecord.generation_status.in_(("pending", "generating")),
                )
            ).scalar()
            return bool(count)

    def list_by_analysis_history(
        self,
        analysis_history_id: int,
        *,
        current_only: bool = False,
    ) -> List[AIOpinionRecord]:
        conditions = [AIOpinionRecord.analysis_history_id == int(analysis_history_id)]
        if current_only:
            conditions.append(AIOpinionRecord.is_current.is_(True))
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(AIOpinionRecord)
                    .where(*conditions)
                    .order_by(desc(AIOpinionRecord.version), desc(AIOpinionRecord.id))
                ).scalars().all()
            )

    def list_by_stock_codes(
        self,
        stock_codes: Sequence[str],
        *,
        current_only: bool = False,
        limit: int = 100,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Tuple[AIOpinionRecord, AnalysisHistory]], int]:
        normalized_codes = [
            str(code or "").strip().upper()
            for code in stock_codes
            if str(code or "").strip()
        ]
        conditions = [
            AnalysisHistory.code.in_(normalized_codes),
            or_(
                AnalysisHistory.report_type.is_(None),
                AnalysisHistory.report_type != "market_review",
            ),
        ]
        if not normalized_codes:
            return [], 0
        if current_only:
            conditions.append(AIOpinionRecord.is_current.is_(True))
        normalized_page = max(1, int(page))
        normalized_page_size = max(1, min(int(page_size), 100))
        with self.db.get_session() as session:
            total = int(session.execute(
                select(func.count(AIOpinionRecord.id))
                .select_from(AIOpinionRecord)
                .join(AnalysisHistory, AIOpinionRecord.analysis_history_id == AnalysisHistory.id)
                .where(*conditions)
            ).scalar() or 0)
            rows = list(
                session.execute(
                    select(AIOpinionRecord, AnalysisHistory)
                    .join(AnalysisHistory, AIOpinionRecord.analysis_history_id == AnalysisHistory.id)
                    .where(*conditions)
                    .order_by(
                        desc(AIOpinionRecord.created_at),
                        desc(AnalysisHistory.created_at),
                        desc(AIOpinionRecord.version),
                        desc(AIOpinionRecord.id),
                    )
                    .offset((normalized_page - 1) * normalized_page_size)
                    .limit(normalized_page_size)
                ).all()
            )
            return rows, total

    def get_current_by_analysis_history(
        self,
        analysis_history_id: int,
    ) -> Optional[AIOpinionRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(AIOpinionRecord)
                .where(
                    AIOpinionRecord.analysis_history_id == int(analysis_history_id),
                    AIOpinionRecord.is_current.is_(True),
                )
                .order_by(desc(AIOpinionRecord.version), desc(AIOpinionRecord.id))
                .limit(1)
            ).scalar_one_or_none()

    def mark_generating(self, opinion_id: int) -> Optional[AIOpinionRecord]:
        def write_operation(session):
            row = session.execute(
                select(AIOpinionRecord).where(AIOpinionRecord.id == int(opinion_id)).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.generation_status != "pending":
                raise AIOpinionStateTransitionError(
                    f"ai_opinion_status_not_pending:{row.generation_status}"
                )
            row.generation_status = "generating"
            row.error_message = None
            row.updated_at = utc_naive_now()
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

        return self.db._run_write_transaction(
            f"mark_ai_opinion_generating[{int(opinion_id)}]",
            write_operation,
        )

    def mark_completed(
        self,
        opinion_id: int,
        *,
        content: str,
        conclusion: str,
        output_json: str,
        evidence_json: Optional[str],
        risks_json: Optional[str],
        limitations_json: Optional[str],
        watch_items_json: Optional[str],
        model: Optional[str],
        provider: Optional[str],
        temperature: Optional[float],
        prompt_version: Optional[str],
        audit_metadata_json: Optional[str],
        context_hash: Optional[str],
        generated_at,
    ) -> Optional[AIOpinionRecord]:
        def write_operation(session):
            row = session.execute(
                select(AIOpinionRecord).where(AIOpinionRecord.id == int(opinion_id)).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.generation_status != "generating":
                raise AIOpinionStateTransitionError(
                    f"ai_opinion_status_not_generating:{row.generation_status}"
                )
            now_value = utc_naive_now()
            if row.analysis_history_id is not None:
                for stale in session.execute(
                    select(AIOpinionRecord).where(
                        AIOpinionRecord.analysis_history_id == row.analysis_history_id,
                        AIOpinionRecord.is_current.is_(True),
                        AIOpinionRecord.id != row.id,
                    )
                ).scalars().all():
                    stale.is_current = False
                    stale.updated_at = now_value
            row.generation_status = "completed"
            row.content = content
            row.conclusion = conclusion
            row.output_json = output_json
            row.evidence_json = evidence_json
            row.risks_json = risks_json
            row.limitations_json = limitations_json
            row.watch_items_json = watch_items_json
            row.model = model
            row.provider = provider
            row.temperature = temperature
            row.prompt_version = prompt_version
            row.audit_metadata_json = audit_metadata_json
            row.context_hash = context_hash
            row.generated_at = generated_at
            row.error_message = None
            row.is_current = True
            row.updated_at = now_value
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row
        return self.db._run_write_transaction(
            f"mark_ai_opinion_completed[{int(opinion_id)}]",
            write_operation,
        )

    def mark_failed(
        self,
        opinion_id: int,
        *,
        error_message: str,
        retry_count: Optional[int] = None,
    ) -> Optional[AIOpinionRecord]:
        return self._update_status(
            opinion_id,
            generation_status="failed",
            error_message=error_message,
            retry_count=retry_count,
            increment_retry=retry_count is None,
        )

    def mark_rejected(
        self,
        opinion_id: int,
        *,
        error_message: str,
    ) -> Optional[AIOpinionRecord]:
        return self._update_status(
            opinion_id,
            generation_status="rejected",
            error_message=error_message,
            increment_retry=True,
        )

    def _update_status(
        self,
        opinion_id: int,
        *,
        generation_status: str,
        error_message: Optional[str],
        retry_count: Optional[int] = None,
        increment_retry: bool = False,
    ) -> Optional[AIOpinionRecord]:
        def write_operation(session):
            row = session.execute(
                select(AIOpinionRecord).where(AIOpinionRecord.id == int(opinion_id)).limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.generation_status not in {"pending", "generating"}:
                raise AIOpinionStateTransitionError(
                    f"ai_opinion_status_not_mutable:{row.generation_status}"
                )
            row.generation_status = generation_status
            row.error_message = error_message
            row.updated_at = utc_naive_now()
            if retry_count is not None:
                row.retry_count = int(retry_count)
            elif increment_retry:
                row.retry_count = int(row.retry_count or 0) + 1
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row
        return self.db._run_write_transaction(
            f"update_ai_opinion_status[{int(opinion_id)}:{generation_status}]",
            write_operation,
        )
