# -*- coding: utf-8 -*-
"""Persistence operations for versioned investment principles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import and_, asc, desc, func, or_, select, update
from src.storage import (
    DatabaseManager,
    InvestmentPrinciple,
    InvestmentPrincipleSource,
    InvestmentPrincipleVersion,
    utc_naive_now,
)


class InvestmentPrincipleRepositoryError(Exception):
    """Base error for persistence failures in the investment principle repository."""


class InvestmentPrincipleNotFoundError(InvestmentPrincipleRepositoryError):
    """Raised when a requested principle or source does not exist."""


class InvestmentPrincipleConcurrencyError(InvestmentPrincipleRepositoryError):
    """Raised when an optimistic expected version or status is stale."""


@dataclass
class InvestmentPrincipleDetail:
    principle: InvestmentPrinciple
    version: InvestmentPrincipleVersion
    sources: List[InvestmentPrincipleSource]


@dataclass
class InvestmentPrincipleVersionPage:
    items: List[InvestmentPrincipleVersion]
    total: int
    page: int
    page_size: int


@dataclass
class InvestmentPrincipleListItem:
    principle: InvestmentPrinciple
    version: InvestmentPrincipleVersion
    source_count: int


@dataclass
class InvestmentPrincipleListPage:
    items: List[InvestmentPrincipleListItem]
    total: int
    page: int
    page_size: int


class InvestmentPrincipleRepository:
    """Persistence boundary for investment principle identities and versions."""

    _LIST_SORT_COLUMNS = {
        "updated_at": InvestmentPrinciple.updated_at,
        "created_at": InvestmentPrinciple.created_at,
        "title": InvestmentPrincipleVersion.title,
        "status": InvestmentPrinciple.status,
    }

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def create_principle_with_initial_version(
        self,
        fields: Dict[str, Any],
        sources: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> InvestmentPrincipleDetail:
        """Create the identity, version 1, and optional sources atomically."""
        version_fields = {
            key: fields[key]
            for key in (
                "title",
                "statement",
                "rationale",
                "category",
                "severity",
                "scope_type",
                "scope_market",
                "scope_stock_code",
                "change_note",
            )
            if key in fields
        }
        status = fields.get("status", "draft")

        def write_operation(session):
            principle = InvestmentPrinciple(status=status, current_version=1)
            session.add(principle)
            session.flush()

            version = InvestmentPrincipleVersion(
                principle_id=principle.id,
                version=1,
                **version_fields,
            )
            session.add(version)
            session.flush()
            created_sources = self._add_source_rows(session, version.id, sources or [])
            session.flush()

            session.refresh(principle)
            session.refresh(version)
            for source in created_sources:
                session.refresh(source)
            self._expunge_all(session, [principle, version, *created_sources])
            return InvestmentPrincipleDetail(principle, version, created_sources)

        return self.db._run_write_transaction(
            "create_investment_principle_with_initial_version",
            write_operation,
        )

    def get_principle_by_id(self, principle_id: int) -> Optional[InvestmentPrinciple]:
        with self.db.get_session() as session:
            return session.execute(
                select(InvestmentPrinciple)
                .where(InvestmentPrinciple.id == int(principle_id))
                .limit(1)
            ).scalar_one_or_none()

    def get_current_version(self, principle_id: int) -> Optional[InvestmentPrincipleVersion]:
        with self.db.get_session() as session:
            return session.execute(
                select(InvestmentPrincipleVersion)
                .join(
                    InvestmentPrinciple,
                    InvestmentPrincipleVersion.principle_id == InvestmentPrinciple.id,
                )
                .where(
                    InvestmentPrinciple.id == int(principle_id),
                    InvestmentPrincipleVersion.version == InvestmentPrinciple.current_version,
                )
                .limit(1)
            ).scalar_one_or_none()

    def get_principle_detail(self, principle_id: int) -> Optional[InvestmentPrincipleDetail]:
        with self.db.get_session() as session:
            principle = session.execute(
                select(InvestmentPrinciple)
                .where(InvestmentPrinciple.id == int(principle_id))
                .limit(1)
            ).scalar_one_or_none()
            if principle is None:
                return None
            version = session.execute(
                select(InvestmentPrincipleVersion).where(
                    InvestmentPrincipleVersion.principle_id == principle.id,
                    InvestmentPrincipleVersion.version == principle.current_version,
                ).limit(1)
            ).scalar_one_or_none()
            if version is None:
                raise InvestmentPrincipleRepositoryError(
                    f"current_version_missing:{principle.id}:{principle.current_version}"
                )
            sources = list(session.execute(
                select(InvestmentPrincipleSource)
                .where(InvestmentPrincipleSource.principle_version_id == version.id)
                .order_by(asc(InvestmentPrincipleSource.created_at), asc(InvestmentPrincipleSource.id))
            ).scalars().all())
            return InvestmentPrincipleDetail(principle, version, sources)

    def create_next_version(
        self,
        principle_id: int,
        expected_current_version: int,
        fields: Dict[str, Any],
        sources: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> InvestmentPrincipleDetail:
        """Create the next immutable version using an optimistic version guard."""
        expected = int(expected_current_version)
        version_fields = {
            key: fields[key]
            for key in (
                "title",
                "statement",
                "rationale",
                "category",
                "severity",
                "scope_type",
                "scope_market",
                "scope_stock_code",
                "change_note",
            )
            if key in fields
        }

        def write_operation(session):
            principle = session.execute(
                select(InvestmentPrinciple)
                .where(InvestmentPrinciple.id == int(principle_id))
                .limit(1)
            ).scalar_one_or_none()
            if principle is None:
                raise InvestmentPrincipleNotFoundError(f"investment_principle_not_found:{principle_id}")

            next_version = expected + 1
            result = session.execute(
                update(InvestmentPrinciple)
                .where(
                    InvestmentPrinciple.id == int(principle_id),
                    InvestmentPrinciple.current_version == expected,
                )
                .values(current_version=next_version, updated_at=utc_naive_now())
            )
            if result.rowcount != 1:
                raise InvestmentPrincipleConcurrencyError(
                    f"investment_principle_version_conflict:{principle_id}:{expected}"
                )

            version = InvestmentPrincipleVersion(
                principle_id=int(principle_id),
                version=next_version,
                **version_fields,
            )
            session.add(version)
            session.flush()
            created_sources = self._add_source_rows(session, version.id, sources or [])
            session.flush()
            principle.current_version = next_version
            principle.updated_at = utc_naive_now()
            session.refresh(principle)
            session.refresh(version)
            for source in created_sources:
                session.refresh(source)
            self._expunge_all(session, [principle, version, *created_sources])
            return InvestmentPrincipleDetail(principle, version, created_sources)

        return self.db._run_write_transaction(
            f"create_investment_principle_next_version[{int(principle_id)}]",
            write_operation,
        )

    def list_versions(self, principle_id: int, page: int = 1, page_size: int = 20) -> InvestmentPrincipleVersionPage:
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        with self.db.get_session() as session:
            principle_exists = session.execute(
                select(InvestmentPrinciple.id)
                .where(InvestmentPrinciple.id == int(principle_id))
                .limit(1)
            ).scalar_one_or_none()
            if principle_exists is None:
                raise InvestmentPrincipleNotFoundError(f"investment_principle_not_found:{principle_id}")
            total = int(session.execute(
                select(func.count(InvestmentPrincipleVersion.id)).where(
                    InvestmentPrincipleVersion.principle_id == int(principle_id)
                )
            ).scalar() or 0)
            rows = list(session.execute(
                select(InvestmentPrincipleVersion)
                .where(InvestmentPrincipleVersion.principle_id == int(principle_id))
                .order_by(desc(InvestmentPrincipleVersion.version), desc(InvestmentPrincipleVersion.id))
                .offset((safe_page - 1) * safe_page_size)
                .limit(safe_page_size)
            ).scalars().all())
            return InvestmentPrincipleVersionPage(rows, total, safe_page, safe_page_size)

    def add_sources_to_version(
        self,
        principle_version_id: int,
        sources: Sequence[Dict[str, Any]],
    ) -> List[InvestmentPrincipleSource]:
        def write_operation(session):
            version_exists = session.execute(
                select(InvestmentPrincipleVersion.id)
                .where(InvestmentPrincipleVersion.id == int(principle_version_id))
                .limit(1)
            ).scalar_one_or_none()
            if version_exists is None:
                raise InvestmentPrincipleNotFoundError(
                    f"investment_principle_version_not_found:{principle_version_id}"
                )
            rows = self._add_source_rows(session, int(principle_version_id), sources)
            session.flush()
            for row in rows:
                session.refresh(row)
            self._expunge_all(session, rows)
            return rows

        return self.db._run_write_transaction(
            f"add_investment_principle_sources[{int(principle_version_id)}]",
            write_operation,
        )

    def list_sources_for_version(self, principle_version_id: int) -> List[InvestmentPrincipleSource]:
        with self.db.get_session() as session:
            return list(session.execute(
                select(InvestmentPrincipleSource)
                .where(InvestmentPrincipleSource.principle_version_id == int(principle_version_id))
                .order_by(asc(InvestmentPrincipleSource.created_at), asc(InvestmentPrincipleSource.id))
            ).scalars().all())

    def get_source_by_id(self, source_id: int) -> Optional[InvestmentPrincipleSource]:
        with self.db.get_session() as session:
            return session.execute(
                select(InvestmentPrincipleSource)
                .where(InvestmentPrincipleSource.id == int(source_id))
                .limit(1)
            ).scalar_one_or_none()

    def update_source_status(
        self,
        source_id: int,
        source_status: str,
        updated_at=None,
    ) -> Optional[InvestmentPrincipleSource]:
        def write_operation(session):
            row = session.execute(
                select(InvestmentPrincipleSource)
                .where(InvestmentPrincipleSource.id == int(source_id))
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            row.source_status = source_status
            row.updated_at = updated_at or utc_naive_now()
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

        return self.db._run_write_transaction(
            f"update_investment_principle_source_status[{int(source_id)}]",
            write_operation,
        )

    def update_principle_status(
        self,
        principle_id: int,
        expected_status: str,
        new_status: str,
        status_changed_at=None,
        *,
        activated_at=None,
        archived_at=None,
        rejected_at=None,
    ) -> Optional[InvestmentPrinciple]:
        def write_operation(session):
            existing = session.execute(
                select(InvestmentPrinciple.id)
                .where(InvestmentPrinciple.id == int(principle_id))
                .limit(1)
            ).scalar_one_or_none()
            if existing is None:
                return None
            values = {
                "status": new_status,
                "status_changed_at": status_changed_at or utc_naive_now(),
                "updated_at": utc_naive_now(),
            }
            if activated_at is not None:
                values["activated_at"] = activated_at
            if archived_at is not None:
                values["archived_at"] = archived_at
            if rejected_at is not None:
                values["rejected_at"] = rejected_at
            result = session.execute(
                update(InvestmentPrinciple)
                .where(
                    InvestmentPrinciple.id == int(principle_id),
                    InvestmentPrinciple.status == expected_status,
                )
                .values(**values)
            )
            if result.rowcount != 1:
                raise InvestmentPrincipleConcurrencyError(
                    f"investment_principle_status_conflict:{principle_id}:{expected_status}"
                )
            row = session.get(InvestmentPrinciple, int(principle_id))
            session.refresh(row)
            session.expunge(row)
            return row

        return self.db._run_write_transaction(
            f"update_investment_principle_status[{int(principle_id)}]",
            write_operation,
        )

    def list_current(
        self,
        *,
        status: Optional[str] = None,
        category: Optional[str] = None,
        severity: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_market: Optional[str] = None,
        scope_stock_code: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> InvestmentPrincipleListPage:
        safe_page = max(1, int(page))
        safe_page_size = max(1, min(int(page_size), 100))
        conditions = [
            InvestmentPrincipleVersion.principle_id == InvestmentPrinciple.id,
            InvestmentPrincipleVersion.version == InvestmentPrinciple.current_version,
        ]
        if status:
            conditions.append(InvestmentPrinciple.status == status)
        if category:
            conditions.append(InvestmentPrincipleVersion.category == category)
        if severity:
            conditions.append(InvestmentPrincipleVersion.severity == severity)
        if scope_type:
            conditions.append(InvestmentPrincipleVersion.scope_type == scope_type)
        if scope_market:
            conditions.append(InvestmentPrincipleVersion.scope_market == scope_market)
        if scope_stock_code:
            conditions.append(InvestmentPrincipleVersion.scope_stock_code == scope_stock_code)
        if keyword:
            term = f"%{keyword.strip()}%"
            conditions.append(or_(
                InvestmentPrincipleVersion.title.ilike(term),
                InvestmentPrincipleVersion.statement.ilike(term),
                InvestmentPrincipleVersion.rationale.ilike(term),
            ))

        order_column = self._LIST_SORT_COLUMNS.get(sort_by, InvestmentPrinciple.updated_at)
        order = asc(order_column) if str(sort_order).lower() == "asc" else desc(order_column)
        with self.db.get_session() as session:
            total = int(session.execute(
                select(func.count(InvestmentPrinciple.id))
                .select_from(InvestmentPrinciple)
                .join(InvestmentPrincipleVersion, and_(*conditions[:2]))
                .where(*conditions[2:])
            ).scalar() or 0)
            rows = session.execute(
                select(
                    InvestmentPrinciple,
                    InvestmentPrincipleVersion,
                    func.count(InvestmentPrincipleSource.id),
                )
                .select_from(InvestmentPrinciple)
                .join(InvestmentPrincipleVersion, and_(*conditions[:2]))
                .outerjoin(
                    InvestmentPrincipleSource,
                    InvestmentPrincipleSource.principle_version_id == InvestmentPrincipleVersion.id,
                )
                .where(*conditions[2:])
                .group_by(InvestmentPrinciple.id, InvestmentPrincipleVersion.id)
                .order_by(order, desc(InvestmentPrinciple.id))
                .offset((safe_page - 1) * safe_page_size)
                .limit(safe_page_size)
            ).all()
            items = [InvestmentPrincipleListItem(principle, version, int(source_count)) for principle, version, source_count in rows]
            return InvestmentPrincipleListPage(items, total, safe_page, safe_page_size)

    @staticmethod
    def _add_source_rows(
        session,
        principle_version_id: int,
        sources: Iterable[Dict[str, Any]],
    ) -> List[InvestmentPrincipleSource]:
        rows = [
            InvestmentPrincipleSource(
                principle_version_id=int(principle_version_id),
                **dict(source),
            )
            for source in sources
        ]
        session.add_all(rows)
        return rows

    @staticmethod
    def _expunge_all(session, rows: Iterable[Any]) -> None:
        for row in rows:
            session.expunge(row)
