# -*- coding: utf-8 -*-
"""unittest coverage for AI opinion versioning semantics."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import ModuleType

from sqlalchemy.exc import IntegrityError

if "dotenv" not in sys.modules:
    dotenv_stub = ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
    sys.modules["dotenv"] = dotenv_stub

from src.config import Config
from src.repositories.ai_opinion_repo import AIOpinionVersionConflictError
from src.services.ai_opinion_service import (
    AIOpinionConflictError,
    AIOpinionNotFoundError,
    AIOpinionService,
)
from src.storage import AIOpinionRecord, AnalysisHistory, DatabaseManager


class AIOpinionServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "ai_opinion_service.db")
        os.environ["DATABASE_PATH"] = self._db_path
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.service = AIOpinionService(db_manager=self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if self._old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_database_path
        self._temp_dir.cleanup()

    def _seed_history(self, code: str = "AAPL") -> int:
        with self.db.session_scope() as session:
            row = AnalysisHistory(
                query_id=f"query-{code}",
                code=code,
                name="Mock Stock",
                report_type="stock",
                analysis_summary="existing analysis",
                raw_result='{"risk_summary":"watch execution"}',
                created_at=datetime(2026, 7, 10, 11, 0, 0),
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def test_create_pending_generation_does_not_override_current(self) -> None:
        history_id = self._seed_history()
        completed = self.service.create_opinion(
            analysis_history_id=history_id,
            content="first review",
            conclusion="first conclusion",
            output_json={"schema_version": "ai-opinion-output-v1"},
            generation_status="completed",
            is_current=True,
        )
        pending = self.service.create_pending_generation(analysis_history_id=history_id)

        self.assertTrue(completed["is_current"])
        self.assertFalse(pending["is_current"])
        self.assertEqual(pending["generation_status"], "pending")

        current = self.service.list_opinions(analysis_history_id=history_id, current_only=True)
        self.assertEqual(current["total"], 1)
        self.assertEqual(current["items"][0]["id"], completed["id"])

    def test_regenerate_creates_new_pending_version(self) -> None:
        history_id = self._seed_history()
        completed = self.service.create_opinion(
            analysis_history_id=history_id,
            content="first review",
            conclusion="first conclusion",
            output_json={"schema_version": "ai-opinion-output-v1"},
            generation_status="completed",
            is_current=True,
        )

        next_version = self.service.regenerate_opinion(completed["id"])
        self.assertEqual(next_version["version"], 2)
        self.assertEqual(next_version["generation_status"], "pending")
        self.assertFalse(next_version["is_current"])

    def test_create_requires_existing_history(self) -> None:
        with self.assertRaises(AIOpinionNotFoundError):
            self.service.create_opinion(
                analysis_history_id=999999,
                conclusion="missing history",
            )

    def test_service_surfaces_repository_conflicts(self) -> None:
        history_id = self._seed_history()

        class ConflictRepo:
            db = self.db

            @staticmethod
            def create_version(_fields):
                raise AIOpinionVersionConflictError("simulated conflict")

            @staticmethod
            def get(_opinion_id):
                return None

            @staticmethod
            def list_by_analysis_history(_analysis_history_id, current_only=False):
                return []

            @staticmethod
            def has_inflight_generation(_analysis_history_id):
                return False

        service = AIOpinionService(repo=ConflictRepo(), db_manager=self.db)
        with self.assertRaises(AIOpinionConflictError):
            service.create_pending_generation(analysis_history_id=history_id)

    def test_database_constraints_allow_deleted_source_rows_and_keep_single_current(self) -> None:
        history_id = self._seed_history()
        created = self.service.create_opinion(
            analysis_history_id=history_id,
            content="first review",
            conclusion="first conclusion",
            output_json={"schema_version": "ai-opinion-output-v1"},
            generation_status="completed",
            is_current=True,
        )
        self.assertEqual(created["version"], 1)

        session = self.db.get_session()
        try:
            session.add(
                AIOpinionRecord(
                    analysis_history_id=history_id,
                    version=1,
                    is_current=False,
                    generation_status="failed",
                    source_status="available",
                    conclusion="duplicate version",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()
        finally:
            session.close()

        session = self.db.get_session()
        try:
            session.add(
                AIOpinionRecord(
                    analysis_history_id=None,
                    version=1,
                    is_current=True,
                    generation_status="completed",
                    source_status="deleted",
                    conclusion="archived opinion",
                )
            )
            session.commit()
        finally:
            session.close()

        current = self.service.list_opinions(analysis_history_id=history_id, current_only=True)
        self.assertEqual(current["total"], 1)
        self.assertEqual(current["items"][0]["version"], 1)


if __name__ == "__main__":
    unittest.main()
