# -*- coding: utf-8 -*-
"""Regeneration and concurrency coverage for AI opinion generation."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import ModuleType
from unittest.mock import MagicMock

if "dotenv" not in sys.modules:
    dotenv_stub = ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
    sys.modules["dotenv"] = dotenv_stub

from src.config import Config
from src.repositories.ai_opinion_repo import AIOpinionStateTransitionError
from src.services.ai_opinion_generation_service import AIOpinionGenerationService
from src.services.ai_opinion_service import AIOpinionService
from src.storage import AnalysisHistory, DatabaseManager


class _CountingBackend:
    def __init__(self, payload: str):
        self.payload = payload
        self.calls = 0
        self._lock = threading.Lock()
        self._started = threading.Event()
        self._release = threading.Event()

    def generate(self, user_prompt, generation_config, *, system_prompt, response_validator, audit_context):
        del user_prompt, generation_config, system_prompt, response_validator, audit_context
        with self._lock:
            self.calls += 1
        self._started.set()
        self._release.wait(timeout=2)
        return MagicMock(
            text=self.payload,
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )


class AIOpinionRegenerateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "ai_opinion_regenerate.db")
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

    @staticmethod
    def _valid_payload(summary: str) -> str:
        return (
            '{"schema_version":"ai-opinion-output-v1","summary":"%s","key_findings":["k"],'
            '"supporting_evidence":[{"statement":"e","source_type":"analysis_history","source_ref":"analysis_summary"}],'
            '"risks":["r"],"uncertainties":["u"],"limitations":["l"],"things_to_watch":["w"],'
            '"investment_discipline_notes":["d"],"confidence":{"level":"medium","rationale":"c"},'
            '"disclaimer":"disc"}'
        ) % summary

    def test_regenerate_failure_keeps_previous_current(self) -> None:
        history_id = self._seed_history()
        completed = self.opinion_service.create_opinion(
            analysis_history_id=history_id,
            content="v1 content",
            conclusion="v1 summary",
            output_json={"schema_version": "ai-opinion-output-v1"},
            generation_status="completed",
            is_current=True,
        )
        pending = self.opinion_service.regenerate_opinion(completed["id"])
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text="not json",
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )

        with self.assertRaises(Exception):
            AIOpinionGenerationService(
                db_manager=self.db,
                opinion_service=self.opinion_service,
                analyzer=analyzer,
            ).generate(pending["id"])

        version1 = self.opinion_service.get_opinion(completed["id"])
        version2 = self.opinion_service.get_opinion(pending["id"])
        self.assertTrue(version1["is_current"])
        self.assertEqual(version1["version"], 1)
        self.assertEqual(version2["version"], 2)
        self.assertEqual(version2["generation_status"], "failed")
        self.assertFalse(version2["is_current"])

    def test_regenerate_success_promotes_new_version(self) -> None:
        history_id = self._seed_history()
        completed = self.opinion_service.create_opinion(
            analysis_history_id=history_id,
            content="v1 content",
            conclusion="v1 summary",
            output_json={"schema_version": "ai-opinion-output-v1"},
            generation_status="completed",
            is_current=True,
        )
        pending = self.opinion_service.regenerate_opinion(completed["id"])
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value.generate.return_value = MagicMock(
            text=self._valid_payload("v2 summary"),
            model="openai/gpt-4o-mini",
            provider="openai",
            backend="litellm",
            usage={},
        )

        result = AIOpinionGenerationService(
            db_manager=self.db,
            opinion_service=self.opinion_service,
            analyzer=analyzer,
        ).generate(pending["id"])

        version1 = self.opinion_service.get_opinion(completed["id"])
        version2 = self.opinion_service.get_opinion(pending["id"])
        self.assertEqual(result["id"], pending["id"])
        self.assertFalse(version1["is_current"])
        self.assertTrue(version2["is_current"])
        self.assertEqual(version2["generation_status"], "completed")

    def test_concurrent_execution_allows_single_generation_attempt(self) -> None:
        history_id = self._seed_history()
        pending = self.opinion_service.create_pending_generation(analysis_history_id=history_id)
        backend = _CountingBackend(self._valid_payload("concurrent summary"))
        analyzer = MagicMock()
        analyzer._get_generation_backend.return_value = backend
        service = AIOpinionGenerationService(
            db_manager=self.db,
            opinion_service=self.opinion_service,
            analyzer=analyzer,
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future1 = executor.submit(service.generate, pending["id"])
            self.assertTrue(backend._started.wait(timeout=2))
            future2 = executor.submit(service.generate, pending["id"])
            backend._release.set()
            result1 = future1.result(timeout=2)
            with self.assertRaises(AIOpinionStateTransitionError):
                future2.result(timeout=2)

        refreshed = self.opinion_service.get_opinion(pending["id"])
        self.assertEqual(backend.calls, 1)
        self.assertEqual(result1["generation_status"], "completed")
        self.assertEqual(refreshed["generation_status"], "completed")
        self.assertTrue(refreshed["is_current"])
        self.assertEqual(refreshed["retry_count"], 0)


if __name__ == "__main__":
    unittest.main()
