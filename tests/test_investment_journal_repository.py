# -*- coding: utf-8 -*-
"""Repository coverage for investment journal structuring state transitions."""

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
from src.repositories.investment_journal_repo import InvestmentJournalRepository
from src.storage import DatabaseManager


class InvestmentJournalRepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "investment_journal_repo.db")
        os.environ["DATABASE_PATH"] = self._db_path
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.repo = InvestmentJournalRepository(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if self._old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_database_path
        self._temp_dir.cleanup()

    def test_update_manual_entry_clears_structured_fields_on_raw_content_change(self) -> None:
        row = self.repo.create(
            {
                "stock_code": "AAPL",
                "market": "us",
                "entry_type": "manual",
                "raw_content": "old note",
                "structured_output_json": '{"summary":"old"}',
                "ai_processing_status": "completed",
                "model": "mock-model",
                "provider": "openai",
                "temperature": 0.2,
                "prompt_version": "journal-v1",
                "structured_version": "investment-journal-structured-v1",
                "structured_at": datetime(2026, 7, 10, 12, 0, 0),
                "structured_error": "old error",
            }
        )

        updated = self.repo.update_manual_entry(row.id, raw_content="new note")
        self.assertEqual(updated.raw_content, "new note")
        self.assertIsNone(updated.structured_output_json)
        self.assertEqual(updated.ai_processing_status, "pending")
        self.assertIsNone(updated.model)
        self.assertIsNone(updated.provider)
        self.assertIsNone(updated.temperature)
        self.assertIsNone(updated.prompt_version)
        self.assertIsNone(updated.structured_version)
        self.assertIsNone(updated.structured_at)
        self.assertIsNone(updated.structured_error)

    def test_update_summary_only_keeps_structured_fields(self) -> None:
        row = self.repo.create(
            {
                "stock_code": "AAPL",
                "market": "us",
                "entry_type": "manual",
                "raw_content": "old note",
                "summary_snapshot": "old summary",
                "structured_output_json": '{"summary":"old"}',
                "ai_processing_status": "completed",
                "model": "mock-model",
                "provider": "openai",
                "temperature": 0.2,
                "prompt_version": "journal-v1",
                "structured_version": "investment-journal-structured-v1",
            }
        )

        updated = self.repo.update_manual_entry(row.id, summary_snapshot="new summary")
        self.assertEqual(updated.summary_snapshot, "new summary")
        self.assertIsNotNone(updated.structured_output_json)
        self.assertEqual(updated.ai_processing_status, "completed")


if __name__ == "__main__":
    unittest.main()
