# -*- coding: utf-8 -*-
"""unittest coverage for investment journal stage 1."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import ModuleType

if "dotenv" not in sys.modules:
    dotenv_stub = ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
    sys.modules["dotenv"] = dotenv_stub

from src.config import Config
from src.services.investment_journal_service import (
    InvestmentJournalConflictError,
    InvestmentJournalNotFoundError,
    InvestmentJournalService,
    InvestmentJournalStructuringUnavailableError,
    InvestmentJournalUnsupportedHistoryError,
)
from src.storage import AnalysisHistory, DatabaseManager, InvestmentJournalEntry


class InvestmentJournalServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "investment_journal_service.db")
        os.environ["DATABASE_PATH"] = self._db_path
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.service = InvestmentJournalService(db_manager=self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if self._old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_database_path
        self._temp_dir.cleanup()

    def _seed_history(
        self,
        *,
        code: str = "600519",
        report_type: str = "stock",
        analysis_summary: str = "Trend remains constructive",
        raw_result: str = '{"watch_items":["volume confirmation","support retest"],"risk_summary":"valuation still rich"}',
    ) -> int:
        with self.db.session_scope() as session:
            row = AnalysisHistory(
                query_id=f"query-{code}-{report_type}",
                code=code,
                name="Mock Stock",
                report_type=report_type,
                analysis_summary=analysis_summary,
                raw_result=raw_result,
                created_at=datetime(2026, 7, 10, 10, 0, 0),
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def test_sync_analysis_entry_is_idempotent(self) -> None:
        history_id = self._seed_history()

        first = self.service.sync_analysis_entry(history_id)
        second = self.service.sync_analysis_entry(history_id)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["item"]["summary_snapshot"], "Trend remains constructive")
        self.assertEqual(first["item"]["risk_summary"], "valuation still rich")
        self.assertEqual(first["item"]["watch_items"], ["volume confirmation", "support retest"])

        with self.db.get_session() as session:
            self.assertEqual(
                session.query(InvestmentJournalEntry).filter(
                    InvestmentJournalEntry.source_analysis_history_id == history_id
                ).count(),
                1,
            )

    def test_manual_entry_update_resets_structured_fields(self) -> None:
        created = self.service.create_manual_entry(
            stock_code="00700",
            market="hk",
            raw_content="Keep tracking ad recovery and buyback pace.",
            summary_snapshot="initial note",
        )
        entry_id = created["id"]

        with self.db.session_scope() as session:
            row = session.get(InvestmentJournalEntry, entry_id)
            row.structured_output_json = '{"summary":"old structured result"}'
            row.ai_processing_status = "failed"
            row.model = "mock-model"
            row.provider = "openai"
            row.temperature = 0.2
            row.prompt_version = "journal-v1"
            row.structured_version = "investment-journal-structured-v1"
            row.structured_error = "old error"

        updated = self.service.update_manual_entry(
            entry_id,
            raw_content="Updated note: focus on ads and buyback pace.",
        )

        self.assertEqual(updated["raw_content"], "Updated note: focus on ads and buyback pace.")
        self.assertIsNone(updated["structured_output"])
        self.assertEqual(updated["ai_processing_status"], "pending")
        self.assertIsNone(updated["model"])
        self.assertIsNone(updated["provider"])
        self.assertIsNone(updated["temperature"])
        self.assertIsNone(updated["prompt_version"])
        self.assertIsNone(updated["structured_version"])
        self.assertIsNone(updated["structured_error"])

    def test_list_entries_includes_current_ai_opinion_summary(self) -> None:
        history_id = self._seed_history()
        self.service.sync_analysis_entry(history_id)

        from src.services.ai_opinion_service import AIOpinionService

        opinion = AIOpinionService(db_manager=self.db).create_opinion(
            analysis_history_id=history_id,
            conclusion="Neutral until confirmation arrives.",
            content="Supplemental review for the saved analysis history.",
        )

        listed = self.service.list_entries(stock_code="600519", market="cn", page=1, page_size=20)

        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["current_ai_opinion"]["id"], opinion["id"])
        self.assertEqual(listed["items"][0]["analysis_history"]["id"], history_id)

    def test_sync_analysis_entry_rejects_market_review(self) -> None:
        history_id = self._seed_history(code="MARKET", report_type="market_review")

        with self.assertRaises(InvestmentJournalUnsupportedHistoryError):
            self.service.sync_analysis_entry(history_id)

    def test_update_manual_entry_rejects_analysis_entries(self) -> None:
        history_id = self._seed_history()
        created = self.service.sync_analysis_entry(history_id)

        with self.assertRaises(InvestmentJournalConflictError):
            self.service.update_manual_entry(created["item"]["id"], raw_content="should fail")

    def test_list_entries_normalizes_equivalent_stock_identifiers(self) -> None:
        self.service.create_manual_entry(
            stock_code="600519.SH",
            market="cn",
            raw_content="manual note",
        )
        self.service.create_manual_entry(
            stock_code="HK00700",
            market="hk",
            raw_content="tencent note",
        )

        cn_list = self.service.list_entries(stock_code="sh600519", market="CN", page=1, page_size=20)
        hk_list = self.service.list_entries(stock_code="00700.HK", market="hk", page=1, page_size=20)

        self.assertEqual(cn_list["total"], 1)
        self.assertEqual(cn_list["items"][0]["stock_code"], "600519")
        self.assertEqual(cn_list["items"][0]["market"], "cn")
        self.assertEqual(hk_list["total"], 1)
        self.assertEqual(hk_list["items"][0]["stock_code"], "HK00700")
        self.assertEqual(hk_list["items"][0]["market"], "hk")

    def test_list_entries_supports_entry_type_filter_and_deleted_source_marker(self) -> None:
        history_id = self._seed_history()
        analysis = self.service.sync_analysis_entry(history_id)
        self.service.create_manual_entry(
            stock_code="600519",
            market="cn",
            raw_content="manual note",
        )

        analysis_only = self.service.list_entries(
            stock_code="600519",
            market="cn",
            entry_type="analysis",
            page=1,
            page_size=20,
        )
        manual_only = self.service.list_entries(
            stock_code="600519",
            market="cn",
            entry_type="manual",
            page=1,
            page_size=20,
        )
        self.assertEqual(analysis_only["total"], 1)
        self.assertEqual(analysis_only["items"][0]["entry_type"], "analysis")
        self.assertEqual(manual_only["total"], 1)
        self.assertEqual(manual_only["items"][0]["entry_type"], "manual")

        self.db.delete_analysis_history_records([history_id])
        deleted_item = self.service.get_entry(analysis["item"]["id"])
        self.assertFalse(deleted_item["analysis_history_available"])
        self.assertEqual(deleted_item["source_status"], "deleted")
        self.assertIsNone(deleted_item["analysis_history"])

    def test_get_entry_raises_for_missing_id(self) -> None:
        with self.assertRaises(InvestmentJournalNotFoundError):
            self.service.get_entry(999999)

    def test_get_entry_normalizes_legacy_succeeded_status(self) -> None:
        created = self.service.create_manual_entry(
            stock_code="AAPL",
            market="us",
            raw_content="legacy note",
        )
        with self.db.session_scope() as session:
            row = session.get(InvestmentJournalEntry, created["id"])
            row.ai_processing_status = "succeeded"
        refreshed = self.service.get_entry(created["id"])
        self.assertEqual(refreshed["ai_processing_status"], "completed")

    def test_create_pending_and_retry_structuring_reuse_same_entry(self) -> None:
        created = self.service.create_manual_entry(
            stock_code="AAPL",
            market="us",
            raw_content="observe capital return policy",
        )
        pending = self.service.create_pending_structuring(created["id"])
        self.assertEqual(pending["id"], created["id"])
        self.assertEqual(pending["ai_processing_status"], "pending")

        with self.db.session_scope() as session:
            row = session.get(InvestmentJournalEntry, created["id"])
            row.ai_processing_status = "failed"
            row.structured_output_json = '{"summary":"old"}'
            row.structured_error = "old error"
            row.model = "mock-model"
            row.provider = "openai"
            row.temperature = 0.3
            row.prompt_version = "journal-v1"
            row.structured_version = "investment-journal-structured-v1"

        retried = self.service.retry_structuring(created["id"])
        self.assertEqual(retried["id"], created["id"])
        self.assertEqual(retried["raw_content"], "observe capital return policy")
        self.assertEqual(retried["ai_processing_status"], "pending")
        self.assertIsNone(retried["structured_output"])
        self.assertIsNone(retried["structured_error"])

    def test_create_pending_structuring_rejects_missing_raw_content(self) -> None:
        created = self.service.create_manual_entry(
            stock_code="AAPL",
            market="us",
            raw_content="seed",
        )
        with self.db.session_scope() as session:
            row = session.get(InvestmentJournalEntry, created["id"])
            row.raw_content = None

        with self.assertRaises(InvestmentJournalStructuringUnavailableError):
            self.service.create_pending_structuring(created["id"])


if __name__ == "__main__":
    unittest.main()
