# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from src.config import Config
from src.repositories.investment_principle_repo import (
    InvestmentPrincipleConcurrencyError,
    InvestmentPrincipleNotFoundError,
    InvestmentPrincipleRepository,
)
from src.storage import DatabaseManager, InvestmentPrinciple


class InvestmentPrincipleRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "investment_principle_repo.db")
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{self.db_path}")
        self.repo = InvestmentPrincipleRepository(self.db)

    def tearDown(self) -> None:
        if getattr(self.db, "_engine", None) is not None:
            self.db._engine.dispose(close=True)
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.temp_dir.cleanup()

    @staticmethod
    def _fields(**overrides):
        fields = {
            "title": "Do not average down in a falling trend",
            "statement": "Do not add to a position while the primary trend is falling.",
            "rationale": "Protect capital until the invalidation condition is cleared.",
            "category": "risk_control",
            "severity": "hard",
            "scope_type": "global",
            "scope_market": None,
            "scope_stock_code": None,
            "change_note": "initial version",
        }
        fields.update(overrides)
        return fields

    def test_initial_creation_and_detail(self) -> None:
        created = self.repo.create_principle_with_initial_version(
            self._fields(),
            sources=[
                {"source_type": "manual", "source_excerpt": "My initial rule"},
                {"source_type": "journal", "source_id": "journal-1", "source_excerpt": "A journal excerpt"},
            ],
        )

        self.assertEqual(created.principle.current_version, 1)
        self.assertEqual(created.version.version, 1)
        self.assertEqual(len(created.sources), 2)
        detail = self.repo.get_principle_detail(created.principle.id)
        self.assertIsNotNone(detail)
        self.assertEqual(detail.version.id, created.version.id)
        self.assertEqual([source.source_type for source in detail.sources], ["manual", "journal"])

    def test_initial_creation_rolls_back_principle_version_and_sources_on_source_failure(self) -> None:
        with self.assertRaises(IntegrityError):
            self.repo.create_principle_with_initial_version(
                self._fields(),
                sources=[{"source_type": "journal"}],
            )

        with self.db.get_session() as session:
            self.assertEqual(session.query(InvestmentPrinciple).count(), 0)

    def test_create_next_version_is_atomic_and_preserves_old_version(self) -> None:
        first = self.repo.create_principle_with_initial_version(self._fields())
        second = self.repo.create_next_version(
            first.principle.id,
            expected_current_version=1,
            fields=self._fields(
                statement="Do not add while the primary trend remains below its invalidation level.",
                change_note="clarify invalidation condition",
            ),
            sources=[{"source_type": "opinion", "source_id": "opinion-2"}],
        )

        self.assertEqual(second.principle.current_version, 2)
        self.assertEqual(second.version.version, 2)
        versions = self.repo.list_versions(first.principle.id, page=1, page_size=10)
        self.assertEqual(versions.total, 2)
        self.assertEqual([version.version for version in versions.items], [2, 1])
        self.assertNotEqual(versions.items[0].statement, versions.items[1].statement)
        self.assertEqual(len(self.repo.list_sources_for_version(first.version.id)), 0)
        self.assertEqual(len(self.repo.list_sources_for_version(second.version.id)), 1)

    def test_next_version_source_failure_rolls_back_current_pointer_version_and_sources(self) -> None:
        first = self.repo.create_principle_with_initial_version(
            self._fields(),
            sources=[{"source_type": "manual", "source_excerpt": "v1"}],
        )

        with self.assertRaises(IntegrityError):
            self.repo.create_next_version(
                first.principle.id,
                expected_current_version=1,
                fields=self._fields(statement="v2"),
                sources=[{"source_type": "opinion"}],
            )

        principle = self.repo.get_principle_by_id(first.principle.id)
        self.assertEqual(principle.current_version, 1)
        self.assertEqual(self.repo.list_versions(first.principle.id).total, 1)
        self.assertEqual(len(self.repo.list_sources_for_version(first.version.id)), 1)

    def test_stale_expected_version_has_no_partial_write(self) -> None:
        first = self.repo.create_principle_with_initial_version(self._fields())
        self.repo.create_next_version(first.principle.id, 1, self._fields(statement="v2"))

        with self.assertRaises(InvestmentPrincipleConcurrencyError):
            self.repo.create_next_version(
                first.principle.id,
                1,
                self._fields(statement="stale v3"),
                sources=[{"source_type": "manual", "source_excerpt": "stale"}],
            )

        principle = self.repo.get_principle_by_id(first.principle.id)
        self.assertEqual(principle.current_version, 2)
        self.assertEqual(self.repo.list_versions(first.principle.id).total, 2)
        self.assertEqual(self.repo.list_sources_for_version(first.version.id), [])

    def test_missing_principle_and_version_are_distinguished(self) -> None:
        self.assertIsNone(self.repo.get_principle_by_id(999999))
        self.assertIsNone(self.repo.get_current_version(999999))
        with self.assertRaises(InvestmentPrincipleNotFoundError):
            self.repo.list_versions(999999)
        with self.assertRaises(InvestmentPrincipleNotFoundError):
            self.repo.create_next_version(999999, 1, self._fields())
        with self.assertRaises(InvestmentPrincipleNotFoundError):
            self.repo.add_sources_to_version(999999, [{"source_type": "manual"}])

    def test_source_append_status_update_and_no_delete_operations(self) -> None:
        created = self.repo.create_principle_with_initial_version(self._fields())
        added = self.repo.add_sources_to_version(
            created.version.id,
            [{"source_type": "manual", "source_excerpt": "first"}],
        )
        changed_at = datetime(2026, 7, 13, 12, 0, 0)
        updated = self.repo.update_source_status(added[0].id, "deleted", changed_at)
        self.assertEqual(updated.source_status, "deleted")
        self.assertEqual(updated.updated_at, changed_at)
        self.assertIsNotNone(self.repo.list_sources_for_version(created.version.id)[0])
        self.assertFalse(hasattr(self.repo, "delete_source"))
        self.assertFalse(hasattr(self.repo, "delete_version"))
        self.assertFalse(hasattr(self.repo, "delete_principle"))

    def test_status_update_uses_expected_status_without_state_machine_rules(self) -> None:
        created = self.repo.create_principle_with_initial_version(self._fields())
        changed_at = datetime(2026, 7, 13, 13, 0, 0)
        updated = self.repo.update_principle_status(
            created.principle.id,
            expected_status="draft",
            new_status="archived",
            status_changed_at=changed_at,
            archived_at=changed_at,
        )
        self.assertEqual(updated.status, "archived")
        self.assertEqual(updated.status_changed_at, changed_at)
        self.assertEqual(updated.archived_at, changed_at)

        with self.assertRaises(InvestmentPrincipleConcurrencyError):
            self.repo.update_principle_status(
                created.principle.id,
                expected_status="draft",
                new_status="active",
            )

    def test_list_current_joins_by_current_version_and_supports_filters_paging_and_sorting(self) -> None:
        global_rule = self.repo.create_principle_with_initial_version(self._fields())
        stock_rule = self.repo.create_principle_with_initial_version(
            self._fields(
                title="Position cap for one stock",
                statement="Keep one stock below the position cap.",
                category="position_sizing",
                severity="soft",
                scope_type="stock",
                scope_market="us",
                scope_stock_code="AAPL",
            ),
        )
        self.repo.create_next_version(
            global_rule.principle.id,
            1,
            self._fields(
                statement="Updated global statement.",
                change_note="updated",
            ),
        )

        page = self.repo.list_current(keyword="Updated", page=1, page_size=10)
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].version.version, 2)
        self.assertEqual(page.items[0].source_count, 0)

        stock_page = self.repo.list_current(
            scope_type="stock",
            scope_market="us",
            scope_stock_code="AAPL",
            severity="soft",
            sort_by="title",
            sort_order="asc",
            page=1,
            page_size=1,
        )
        self.assertEqual(stock_page.total, 1)
        self.assertEqual(stock_page.items[0].principle.id, stock_rule.principle.id)


if __name__ == "__main__":
    unittest.main()
