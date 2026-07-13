# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from datetime import datetime

from src.config import Config
from src.repositories.ai_opinion_repo import AIOpinionRepository
from src.repositories.investment_journal_repo import InvestmentJournalRepository
from src.repositories.investment_principle_repo import InvestmentPrincipleRepository
from src.services.investment_principle_service import (
    InvestmentPrincipleConflictError,
    InvestmentPrincipleNotFoundError,
    InvestmentPrincipleService,
    InvestmentPrincipleValidationError,
)
from src.storage import AnalysisHistory, DatabaseManager


class InvestmentPrincipleServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "investment_principle_service.db")
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{self.db_path}")
        self.repo = InvestmentPrincipleRepository(self.db)
        self.journal_repo = InvestmentJournalRepository(self.db)
        self.opinion_repo = AIOpinionRepository(self.db)
        self.service = InvestmentPrincipleService(
            self.repo,
            self.db,
            self.journal_repo,
            self.opinion_repo,
        )

    def tearDown(self) -> None:
        self.db._engine.dispose(close=True)
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.temp_dir.cleanup()

    def _create(self, **overrides):
        fields = {
            "title": "  Position discipline  ",
            "statement": "  Keep risk within the predefined limit.  ",
            "rationale": "  Protect capital.  ",
            "category": "  risk_control  ",
            "severity": " HARD ",
            "scope_type": " GLOBAL ",
        }
        fields.update(overrides)
        return self.service.create_principle(**fields)

    def test_create_normalizes_text_enums_and_always_starts_draft(self) -> None:
        created = self._create()
        self.assertEqual(created.principle.status, "draft")
        self.assertEqual(created.version.title, "Position discipline")
        self.assertEqual(created.version.statement, "Keep risk within the predefined limit.")
        self.assertEqual(created.version.category, "risk_control")
        self.assertEqual(created.version.severity, "hard")
        self.assertEqual(created.version.scope_type, "global")

    def test_create_rejects_non_draft_status_and_invalid_text(self) -> None:
        with self.assertRaises(InvestmentPrincipleValidationError):
            self.service.create_principle(**self._create_kwargs(status="active"))
        for field, value in (("title", " "), ("statement", ""), ("category", "\t")):
            kwargs = self._create_kwargs()
            kwargs[field] = value
            with self.subTest(field=field), self.assertRaises(InvestmentPrincipleValidationError):
                self.service.create_principle(**kwargs)

    def test_create_rejects_invalid_enums_and_length(self) -> None:
        for field, value in (("severity", "strict"), ("scope_type", "portfolio")):
            kwargs = self._create_kwargs()
            kwargs[field] = value
            with self.subTest(field=field), self.assertRaises(InvestmentPrincipleValidationError):
                self.service.create_principle(**kwargs)
        kwargs = self._create_kwargs(title="x" * 201)
        with self.assertRaises(InvestmentPrincipleValidationError):
            self.service.create_principle(**kwargs)

    def test_scope_rules_and_existing_market_stock_normalization(self) -> None:
        stock = self._create(scope_type="stock", scope_market=" US ", scope_stock_code=" aapl ")
        self.assertEqual(stock.version.scope_market, "us")
        self.assertEqual(stock.version.scope_stock_code, "AAPL")

        invalid_cases = [
            {"scope_type": "global", "scope_market": "cn"},
            {"scope_type": "global", "scope_stock_code": "600519"},
            {"scope_type": "market"},
            {"scope_type": "market", "scope_market": "cn", "scope_stock_code": "600519"},
            {"scope_type": "stock", "scope_stock_code": "600519"},
        ]
        for case in invalid_cases:
            with self.subTest(case=case), self.assertRaises(InvestmentPrincipleValidationError):
                self._create(**case)

    def test_source_snapshot_validation_for_manual_journal_and_opinion(self) -> None:
        journal = self.journal_repo.create({
            "stock_code": "AAPL",
            "market": "us",
            "entry_type": "manual",
            "raw_content": "Journal raw content",
            "summary_snapshot": "Journal summary",
            "source_label": "manual",
            "source_status": "available",
            "ai_processing_status": "pending",
        })
        with self.db.get_session() as session:
            history = AnalysisHistory(code="AAPL", name="Apple", created_at=datetime(2026, 7, 13, 10, 0, 0))
            session.add(history)
            session.commit()
            history_id = history.id
        opinion = self.opinion_repo.create_version({
            "analysis_history_id": history_id,
            "generation_status": "completed",
            "title": "Opinion title",
            "content": "Opinion content",
            "conclusion": "Opinion conclusion",
            "output_json": "{\"summary\": \"Opinion JSON\"}",
            "source_status": "available",
            "is_current": True,
        })

        created = self._create(sources=[
            {"source_type": "manual", "source_excerpt": "  Manual note  "},
            {"source_type": "journal", "source_id": journal.id, "source_excerpt": "caller text ignored"},
            {"source_type": "opinion", "source_id": opinion.id, "source_excerpt": "caller text ignored"},
        ])
        self.assertEqual([source.source_excerpt for source in created.sources], [
            "Manual note", "Journal raw content", "Opinion title",
        ])
        self.assertTrue(all(source.source_status == "available" for source in created.sources))

    def test_source_validation_rejects_missing_external_and_duplicate_sources(self) -> None:
        invalid_sources = [
            [{"source_type": "external", "source_excerpt": "x"}],
            [{"source_type": "manual", "source_excerpt": ""}],
            [{"source_type": "manual", "source_id": "1", "source_excerpt": "x"}],
            [{"source_type": "journal", "source_id": 999999}],
            [
                {"source_type": "manual", "source_excerpt": "same"},
                {"source_type": "manual", "source_excerpt": " same "},
            ],
        ]
        for sources in invalid_sources:
            with self.subTest(sources=sources), self.assertRaises(
                (InvestmentPrincipleValidationError, InvestmentPrincipleNotFoundError)
            ):
                self._create(sources=sources)

    def test_update_partial_merge_creates_version_and_preserves_status(self) -> None:
        created = self._create()
        updated = self.service.update_principle(
            created.principle.id,
            expected_current_version=1,
            fields={"title": "Updated title", "change_note": "rename"},
        )
        self.assertEqual(updated.version.version, 2)
        self.assertEqual(updated.version.title, "Updated title")
        self.assertEqual(updated.version.statement, created.version.statement)
        self.assertEqual(updated.principle.status, "draft")

        self.service.activate_principle(created.principle.id)
        active_updated = self.service.update_principle(
            created.principle.id,
            expected_current_version=2,
            fields={"statement": "Updated active statement"},
        )
        self.assertEqual(active_updated.principle.status, "active")
        self.assertIsNotNone(active_updated.principle.activated_at)

    def test_sources_only_update_does_not_create_version(self) -> None:
        created = self._create()
        updated = self.service.update_principle(
            created.principle.id,
            expected_current_version=1,
            fields={},
            sources=[{"source_type": "manual", "source_excerpt": "new evidence"}],
        )
        self.assertEqual(updated.principle.current_version, 1)
        self.assertEqual(len(updated.sources), 1)

        with self.assertRaises(InvestmentPrincipleValidationError):
            self.service.update_principle(
                created.principle.id,
                expected_current_version=1,
                fields={},
            )

    def test_update_rejected_conflicts_restore_then_edit(self) -> None:
        created = self._create()
        self.service.reject_principle(created.principle.id)
        with self.assertRaises(InvestmentPrincipleConflictError):
            self.service.update_principle(
                created.principle.id,
                expected_current_version=1,
                fields={"title": "forbidden"},
            )
        restored = self.service.restore_principle_to_draft(created.principle.id)
        self.assertEqual(restored.principle.status, "draft")
        edited = self.service.update_principle(
            created.principle.id,
            expected_current_version=1,
            fields={"title": "restored edit"},
        )
        self.assertEqual(edited.version.version, 2)

    def test_status_machine_and_timestamp_rules(self) -> None:
        created = self._create()
        active = self.service.activate_principle(created.principle.id)
        self.assertEqual(active.principle.status, "active")
        self.assertIsNotNone(active.principle.activated_at)
        archived = self.service.archive_principle(created.principle.id)
        self.assertEqual(archived.principle.status, "archived")
        self.assertIsNotNone(archived.principle.archived_at)
        reactivated = self.service.activate_principle(created.principle.id)
        self.assertEqual(reactivated.principle.status, "active")
        self.assertEqual(reactivated.principle.archived_at, archived.principle.archived_at)

        self.service.archive_principle(created.principle.id)
        with self.assertRaises(InvestmentPrincipleConflictError):
            self.service.archive_principle(created.principle.id)

        rejected = self._create(title="Rejected")
        self.service.reject_principle(rejected.principle.id)
        with self.assertRaises(InvestmentPrincipleConflictError):
            self.service.activate_principle(rejected.principle.id)

    def test_source_status_machine_and_missing_source(self) -> None:
        created = self._create(sources=[{"source_type": "manual", "source_excerpt": "evidence"}])
        source_id = created.sources[0].id
        deleted = self.service.mark_source_status(source_id, "deleted")
        self.assertEqual(deleted.source_status, "deleted")
        with self.assertRaises(InvestmentPrincipleConflictError):
            self.service.mark_source_status(source_id, "available")
        with self.assertRaises(InvestmentPrincipleNotFoundError):
            self.service.mark_source_status(999999, "deleted")

    def test_list_validation_and_current_version_filters(self) -> None:
        self._create(category="risk_control", severity="hard")
        self._create(
            title="Stock rule",
            category="position_sizing",
            severity="soft",
            scope_type="stock",
            scope_market="us",
            scope_stock_code="AAPL",
        )
        page = self.service.list_principles(
            category=" position_sizing ",
            market=" US ",
            stock_code="aapl",
            page=1,
            page_size=1,
            sort_by="title",
            sort_order="asc",
        )
        self.assertEqual(page.total, 1)
        self.assertEqual(page.items[0].version.scope_stock_code, "AAPL")

        with self.assertRaises(InvestmentPrincipleValidationError):
            self.service.list_principles(page=0)
        with self.assertRaises(InvestmentPrincipleValidationError):
            self.service.list_principles(sort_by="id")
        with self.assertRaises(InvestmentPrincipleValidationError):
            self.service.list_principles(stock_code="AAPL")

    def test_repository_errors_map_to_service_errors(self) -> None:
        with self.assertRaises(InvestmentPrincipleNotFoundError):
            self.service.get_principle(999999)
        created = self._create()
        self.service.update_principle(created.principle.id, expected_current_version=1, fields={"title": "v2"})
        with self.assertRaises(InvestmentPrincipleConflictError):
            self.service.update_principle(created.principle.id, expected_current_version=1, fields={"title": "stale"})

    @staticmethod
    def _create_kwargs(**overrides):
        fields = {
            "title": "Title",
            "statement": "Statement",
            "category": "risk",
            "severity": "advisory",
            "scope_type": "global",
        }
        fields.update(overrides)
        return fields


if __name__ == "__main__":
    unittest.main()
