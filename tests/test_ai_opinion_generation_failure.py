# -*- coding: utf-8 -*-
"""Failure-path coverage for AI opinion generation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import ModuleType
from unittest.mock import MagicMock

if "dotenv" not in sys.modules:
    dotenv_stub = ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
    sys.modules["dotenv"] = dotenv_stub

from src.config import Config
from src.services.ai_opinion_generation_service import AIOpinionGenerationService
from src.services.ai_opinion_service import AIOpinionService
from src.storage import AnalysisHistory, DatabaseManager


class AIOpinionGenerationFailureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "ai_opinion_generation_failure.db")
        os.environ["DATABASE_PATH"] = self._db_path
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.opinion_service = AIOpinionService(db_manager=self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if self._old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_database_path
        self._temp_dir.cleanup()

    def _seed_history(self, *, summary: str = "Apple setup summary") -> int:
        with self.db.session_scope() as session:
            row = AnalysisHistory(
                query_id="query-aapl",
                code="AAPL",
                name="Apple",
                report_type="stock",
                analysis_summary=summary,
                raw_result='{"key_points":["k1"],"risk_warning":"r1"}',
                created_at=datetime(2026, 7, 10, 11, 0, 0),
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def _build_service(self, analyzer: MagicMock) -> AIOpinionGenerationService:
        return AIOpinionGenerationService(
            db_manager=self.db,
            opinion_service=self.opinion_service,
            analyzer=analyzer,
        )

    def test_timeout_marks_failed_and_keeps_current_unchanged(self) -> None:
        history_id = self._seed_history()
        current = self.opinion_service.create_opinion(
            analysis_history_id=history_id,
            content="v1 content",
            conclusion="v1 summary",
            output_json={"schema_version": "ai-opinion-output-v1"},
            generation_status="completed",
            is_current=True,
        )
        pending = self.opinion_service.regenerate_opinion(current["id"])
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.side_effect = TimeoutError("timeout")

        with self.assertRaises(TimeoutError):
            self._build_service(analyzer).generate(pending["id"])

        refreshed_pending = self.opinion_service.get_opinion(pending["id"])
        refreshed_current = self.opinion_service.get_opinion(current["id"])
        self.assertEqual(refreshed_pending["generation_status"], "failed")
        self.assertEqual(refreshed_pending["retry_count"], 1)
        self.assertIn("timeout", refreshed_pending["error_message"])
        self.assertFalse(refreshed_pending["is_current"])
        self.assertEqual(refreshed_current["generation_status"], "completed")
        self.assertTrue(refreshed_current["is_current"])

    def test_invalid_json_marks_failed_without_output(self) -> None:
        history_id = self._seed_history()
        pending = self.opinion_service.create_pending_generation(analysis_history_id=history_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text="not json",
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )

        with self.assertRaises(Exception):
            self._build_service(analyzer).generate(pending["id"])

        refreshed = self.opinion_service.get_opinion(pending["id"])
        self.assertEqual(refreshed["generation_status"], "failed")
        self.assertEqual(refreshed["retry_count"], 1)
        self.assertIsNone(refreshed["output_json"])
        self.assertIn("missing_json_object", refreshed["error_message"])

    def test_empty_response_marks_failed(self) -> None:
        history_id = self._seed_history()
        pending = self.opinion_service.create_pending_generation(analysis_history_id=history_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text="",
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )

        with self.assertRaises(Exception):
            self._build_service(analyzer).generate(pending["id"])

        refreshed = self.opinion_service.get_opinion(pending["id"])
        self.assertEqual(refreshed["generation_status"], "failed")
        self.assertEqual(refreshed["retry_count"], 1)
        self.assertIn("empty_response", refreshed["error_message"])

    def test_schema_incomplete_marks_failed(self) -> None:
        history_id = self._seed_history()
        pending = self.opinion_service.create_pending_generation(analysis_history_id=history_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text='{"schema_version":"ai-opinion-output-v1","key_findings":[],"supporting_evidence":[],"uncertainties":[],"limitations":[],"things_to_watch":[],"investment_discipline_notes":[],"confidence":{"level":"medium","rationale":"c"}}',
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )

        with self.assertRaises(Exception):
            self._build_service(analyzer).generate(pending["id"])

        refreshed = self.opinion_service.get_opinion(pending["id"])
        self.assertEqual(refreshed["generation_status"], "failed")
        self.assertEqual(refreshed["retry_count"], 1)
        self.assertIsNone(refreshed["output_json"])


if __name__ == "__main__":
    unittest.main()
