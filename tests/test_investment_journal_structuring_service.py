# -*- coding: utf-8 -*-
"""Service coverage for investment journal AI structuring."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from types import ModuleType
from unittest.mock import MagicMock

if "dotenv" not in sys.modules:
    dotenv_stub = ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
    sys.modules["dotenv"] = dotenv_stub

from src.config import Config
from src.services.investment_journal_service import InvestmentJournalService
from src.services.investment_journal_structuring_service import InvestmentJournalStructuringService
from src.storage import DatabaseManager


class InvestmentJournalStructuringServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "investment_journal_structuring.db")
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

    def _create_manual_entry(self, raw_content: str = "I plan to keep observing margins.") -> int:
        created = self.service.create_manual_entry(
            stock_code="AAPL",
            market="us",
            raw_content=raw_content,
        )
        return int(created["id"])

    @staticmethod
    def _valid_payload(summary: str = "User note summary") -> str:
        return (
            '{"schema_version":"investment-journal-structured-v1","summary":"%s","journal_type":"research_note",'
            '"investment_thesis":"thesis","reasons":["r1"],"risks":["r2"],"assumptions":["a1"],'
            '"invalidation_conditions":["i1"],"emotions":["calm"],"cognitive_bias":["confirmation bias"],'
            '"follow_up_items":["watch next quarter"],"tags":["long-term"]}'
        ) % summary

    def test_successful_structuring(self) -> None:
        entry_id = self._create_manual_entry()
        self.service.create_pending_structuring(entry_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text=self._valid_payload(),
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )

        result = InvestmentJournalStructuringService(
            db_manager=self.db,
            journal_service=self.service,
            analyzer=analyzer,
        ).structure(entry_id)

        self.assertEqual(result["ai_processing_status"], "completed")
        self.assertIsNotNone(result["structured_output"])
        self.assertEqual(result["structured_version"], "investment-journal-structured-v1")
        self.assertEqual(result["provider"], "openai")

    def test_invalid_json_marks_failed(self) -> None:
        entry_id = self._create_manual_entry()
        self.service.create_pending_structuring(entry_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text="not json",
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )

        with self.assertRaises(Exception):
            InvestmentJournalStructuringService(
                db_manager=self.db,
                journal_service=self.service,
                analyzer=analyzer,
            ).structure(entry_id)

        refreshed = self.service.get_entry(entry_id)
        self.assertEqual(refreshed["ai_processing_status"], "failed")
        self.assertIsNone(refreshed["structured_output"])
        self.assertIn("missing_json_object", refreshed["structured_error"])

    def test_timeout_marks_failed(self) -> None:
        entry_id = self._create_manual_entry()
        self.service.create_pending_structuring(entry_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.side_effect = TimeoutError("timeout")

        with self.assertRaises(TimeoutError):
            InvestmentJournalStructuringService(
                db_manager=self.db,
                journal_service=self.service,
                analyzer=analyzer,
            ).structure(entry_id)

        refreshed = self.service.get_entry(entry_id)
        self.assertEqual(refreshed["ai_processing_status"], "failed")
        self.assertIn("timeout", refreshed["structured_error"])

    def test_schema_fail_marks_failed(self) -> None:
        entry_id = self._create_manual_entry()
        self.service.create_pending_structuring(entry_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text='{"schema_version":"investment-journal-structured-v1","journal_type":"research_note"}',
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )

        with self.assertRaises(Exception):
            InvestmentJournalStructuringService(
                db_manager=self.db,
                journal_service=self.service,
                analyzer=analyzer,
            ).structure(entry_id)

        refreshed = self.service.get_entry(entry_id)
        self.assertEqual(refreshed["ai_processing_status"], "failed")

    def test_retry_reuses_same_entry_and_preserves_raw_content(self) -> None:
        entry_id = self._create_manual_entry("I wrote that I might buy later.")
        self.service.create_pending_structuring(entry_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text=self._valid_payload("first"),
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )
        structuring_service = InvestmentJournalStructuringService(
            db_manager=self.db,
            journal_service=self.service,
            analyzer=analyzer,
        )
        structuring_service.structure(entry_id)

        retry_pending = self.service.retry_structuring(entry_id)
        self.assertEqual(retry_pending["id"], entry_id)
        self.assertEqual(retry_pending["ai_processing_status"], "pending")
        self.assertEqual(retry_pending["raw_content"], "I wrote that I might buy later.")
        self.assertIsNone(retry_pending["structured_output"])


if __name__ == "__main__":
    unittest.main()
