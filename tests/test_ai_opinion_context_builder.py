# -*- coding: utf-8 -*-
"""Unit coverage for AI opinion context builder."""

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
from src.services.ai_opinion_context_builder import AnalysisOpinionContextBuilder
from src.storage import AnalysisHistory, DatabaseManager, DecisionSignalRecord, NewsIntel


class AnalysisOpinionContextBuilderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "ai_opinion_context.db")
        os.environ["DATABASE_PATH"] = self._db_path
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager.get_instance()
        self.builder = AnalysisOpinionContextBuilder(self.db)

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if self._old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_database_path
        self._temp_dir.cleanup()

    def test_builder_keeps_whitelisted_fields_only(self) -> None:
        with self.db.session_scope() as session:
            history = AnalysisHistory(
                query_id="query-aapl",
                code="AAPL",
                name="Apple",
                report_type="stock",
                analysis_summary="Long summary",
                raw_result='{"key_points":["k1","k2"],"risk_warning":"r1","dashboard":{"risk_warning":"r2"}}',
                created_at=datetime(2026, 7, 10, 10, 0, 0),
            )
            session.add(history)
            session.flush()
            session.add(
                DecisionSignalRecord(
                    stock_code="AAPL",
                    stock_name="Apple",
                    market="us",
                    source_type="analysis",
                    source_report_id=history.id,
                    trace_id="trace-1",
                    trigger_source="api",
                    action="buy",
                    action_label="买入",
                    reason="signal reason",
                    risk_summary="signal risk",
                    catalyst_summary="earnings catalyst",
                    watch_conditions="watch support",
                    evidence_json='["e1", "e2"]',
                    plan_quality="minimal",
                    status="active",
                )
            )
            session.add(
                NewsIntel(
                    query_id="query-aapl",
                    code="AAPL",
                    name="Apple",
                    title="Apple launches update",
                    snippet="News snippet",
                    url="https://example.com/aapl",
                    source="Example",
                    published_date=datetime(2026, 7, 10, 9, 0, 0),
                )
            )
            history_id = int(history.id)

        context = self.builder.build(history_id)
        payload = context.model_dump(mode="json")
        self.assertEqual(payload["analysis_history_id"], history_id)
        self.assertNotIn("action", str(payload))
        self.assertNotIn("score", str(payload))
        self.assertIn("analysis_summary", payload)
        self.assertEqual(len(payload["news_evidence"]), 1)

    def test_builder_tracks_truncation_and_source_trace(self) -> None:
        with self.db.session_scope() as session:
            history = AnalysisHistory(
                query_id="query-msft",
                code="MSFT",
                name="Microsoft",
                report_type="stock",
                analysis_summary="Summary",
                raw_result='{"key_points":["k1","k2","k3","k4","k5","k6"],"risk_warning":["r1","r2","r3","r4","r5","r6"]}',
                created_at=datetime(2026, 7, 10, 10, 0, 0),
            )
            session.add(history)
            session.flush()
            history_id = int(history.id)
            for idx in range(8):
                session.add(
                    NewsIntel(
                        query_id="query-msft",
                        code="MSFT",
                        name="Microsoft",
                        title=f"News {idx}",
                        snippet=f"Snippet {idx}",
                        url=f"https://example.com/msft/{idx}",
                        source="Example",
                        published_date=datetime(2026, 7, 10, 9, 0, idx),
                    )
                )

        payload = self.builder.build(history_id).model_dump(mode="json")
        self.assertTrue(payload["truncated"])
        self.assertIn("key_points", payload["source_trace"]["truncated_sections"])
        self.assertIn("risks", payload["source_trace"]["truncated_sections"])
        self.assertIn("news_evidence", payload["source_trace"]["truncated_sections"])
        self.assertEqual(payload["source_trace"]["news_items_used"], 6)
        self.assertEqual(payload["source_trace"]["news_items_total"], 7)
