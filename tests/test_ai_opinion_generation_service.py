# -*- coding: utf-8 -*-
"""Unit coverage for AI opinion generation service."""

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


class AIOpinionGenerationServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "ai_opinion_generation.db")
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

    def _seed_history(self) -> int:
        with self.db.session_scope() as session:
            row = AnalysisHistory(
                query_id="query-aapl",
                code="AAPL",
                name="Apple",
                report_type="stock",
                analysis_summary="Apple setup summary",
                raw_result='{"key_points":["k1"],"risk_warning":"r1"}',
                created_at=datetime(2026, 7, 10, 11, 0, 0),
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def test_generate_completed_opinion(self) -> None:
        history_id = self._seed_history()
        pending = self.opinion_service.create_pending_generation(analysis_history_id=history_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text=(
                '{"schema_version":"ai-opinion-output-v1","summary":"s","key_findings":["k"],'
                '"supporting_evidence":[{"statement":"e","source_type":"analysis_history","source_ref":"analysis_summary"}],'
                '"risks":["r"],"uncertainties":["u"],"limitations":["l"],"things_to_watch":["w"],'
                '"investment_discipline_notes":["d"],"confidence":{"level":"medium","rationale":"c"},'
                '"disclaimer":"disc"}'
            ),
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={"total_tokens": 123},
        )
        service = AIOpinionGenerationService(
            db_manager=self.db,
            opinion_service=self.opinion_service,
            analyzer=analyzer,
        )

        result = service.generate(pending["id"])
        self.assertEqual(result["generation_status"], "completed")
        self.assertTrue(result["is_current"])
        self.assertIsNotNone(result["output_json"])
        self.assertIn("Summary", result["content"])

    def test_generate_rejects_investment_advice(self) -> None:
        history_id = self._seed_history()
        pending = self.opinion_service.create_pending_generation(analysis_history_id=history_id)
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text=(
                '{"schema_version":"ai-opinion-output-v1","summary":"建议买入","key_findings":[],'
                '"supporting_evidence":[],"risks":[],"uncertainties":[],"limitations":[],"things_to_watch":[],'
                '"investment_discipline_notes":[],"confidence":{"level":"low","rationale":"c"},'
                '"disclaimer":"disc"}'
            ),
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )
        service = AIOpinionGenerationService(
            db_manager=self.db,
            opinion_service=self.opinion_service,
            analyzer=analyzer,
        )

        with self.assertRaises(Exception):
            service.generate(pending["id"])
        refreshed = self.opinion_service.get_opinion(pending["id"])
        self.assertEqual(refreshed["generation_status"], "rejected")
        self.assertFalse(refreshed["is_current"])


if __name__ == "__main__":
    unittest.main()
