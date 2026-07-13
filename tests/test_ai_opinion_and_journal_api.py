# -*- coding: utf-8 -*-
"""unittest API coverage for AI opinions and investment journals stage 1."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

if "dotenv" not in sys.modules:
    dotenv_stub = ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
    sys.modules["dotenv"] = dotenv_stub

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

import src.auth as auth
from api.app import create_app
from src.config import Config
from src.services.ai_opinion_service import AIOpinionService
from src.services.task_queue import get_task_queue
from src.storage import AnalysisHistory, DatabaseManager, InvestmentJournalEntry


def _reset_auth_globals() -> None:
    auth._auth_enabled = None
    auth._session_secret = None
    auth._password_hash_salt = None
    auth._password_hash_stored = None
    auth._rate_limit = {}


class AIOpinionAndJournalApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_env_file = os.environ.get("ENV_FILE")
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._env_path = Path(self._temp_dir.name) / ".env"
        self._db_path = Path(self._temp_dir.name) / "ai_opinion_and_journal_api.db"
        self._static_dir = Path(self._temp_dir.name) / "empty-static"
        self._static_dir.mkdir()
        self._env_path.write_text(
            "\n".join(
                [
                    "STOCK_LIST=600519",
                    "GEMINI_API_KEY=test",
                    "ADMIN_AUTH_ENABLED=false",
                    f"DATABASE_PATH={self._db_path}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self._env_path)
        os.environ["DATABASE_PATH"] = str(self._db_path)
        _reset_auth_globals()
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.client = TestClient(create_app(static_dir=Path(self._static_dir)))
        self.db = DatabaseManager.get_instance()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        _reset_auth_globals()
        if self._old_env_file is None:
            os.environ.pop("ENV_FILE", None)
        else:
            os.environ["ENV_FILE"] = self._old_env_file
        if self._old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_database_path
        self._temp_dir.cleanup()

    def _seed_history(self, *, code: str = "600519") -> int:
        with self.db.session_scope() as session:
            row = AnalysisHistory(
                query_id=f"query-{code}",
                code=code,
                name="Mock Stock",
                report_type="stock",
                analysis_summary="saved analysis summary",
                raw_result='{"watch_items":["watch volume"],"risk_summary":"watch pullback"}',
                created_at=datetime(2026, 7, 10, 9, 30, 0),
            )
            session.add(row)
            session.flush()
            return int(row.id)

    @patch("api.v1.endpoints.investment_journals.InvestmentJournalStructuringService.structure")
    def test_journal_api_manual_create_sync_list_and_update(self, mocked_structure) -> None:
        history_id = self._seed_history()
        mocked_structure.return_value = {"ok": True}

        manual_resp = self.client.post(
            "/api/v1/investment-journals/manual",
            json={
                "stock_code": "600519.SH",
                "market": "cn",
                "raw_content": "first manual note",
                "summary_snapshot": "manual summary",
            },
        )
        self.assertEqual(manual_resp.status_code, 202, manual_resp.text)
        accepted = manual_resp.json()
        self.assertTrue(accepted["accepted"])
        self.assertIn("task_id", accepted)
        manual_item = accepted["entry"]
        self.assertEqual(manual_item["entry_type"], "manual")
        self.assertEqual(manual_item["raw_content"], "first manual note")
        self.assertEqual(manual_item["ai_processing_status"], "pending")
        self.assertIn("provider", manual_item)
        self.assertIn("structured_error", manual_item)

        sync_resp = self.client.post(f"/api/v1/investment-journals/sync-analysis/{history_id}")
        self.assertEqual(sync_resp.status_code, 200, sync_resp.text)
        self.assertTrue(sync_resp.json()["created"])

        repeat_sync_resp = self.client.post(f"/api/v1/investment-journals/sync-analysis/{history_id}")
        self.assertEqual(repeat_sync_resp.status_code, 200, repeat_sync_resp.text)
        self.assertFalse(repeat_sync_resp.json()["created"])
        self.assertEqual(
            repeat_sync_resp.json()["item"]["id"],
            sync_resp.json()["item"]["id"],
        )

        list_resp = self.client.get(
            "/api/v1/investment-journals",
            params={"stock_code": "sh600519", "market": "CN", "page": 1, "page_size": 20},
        )
        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        payload = list_resp.json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual({item["entry_type"] for item in payload["items"]}, {"manual", "analysis"})

        analysis_only = self.client.get(
            "/api/v1/investment-journals",
            params={
                "stock_code": "600519",
                "market": "cn",
                "entry_type": "analysis",
                "page": 1,
                "page_size": 20,
            },
        )
        self.assertEqual(analysis_only.status_code, 200, analysis_only.text)
        self.assertEqual(analysis_only.json()["total"], 1)
        self.assertEqual(analysis_only.json()["items"][0]["entry_type"], "analysis")

        patch_resp = self.client.patch(
            f"/api/v1/investment-journals/manual/{manual_item['id']}",
            json={"raw_content": "updated manual note"},
        )
        self.assertEqual(patch_resp.status_code, 202, patch_resp.text)
        update_accepted = patch_resp.json()
        self.assertTrue(update_accepted["accepted"])
        self.assertIn("task_id", update_accepted)
        self.assertEqual(update_accepted["entry"]["raw_content"], "updated manual note")
        self.assertEqual(update_accepted["entry"]["ai_processing_status"], "pending")

    def test_journal_api_rejects_invalid_manual_mutation_targets(self) -> None:
        history_id = self._seed_history()
        sync_resp = self.client.post(f"/api/v1/investment-journals/sync-analysis/{history_id}")
        self.assertEqual(sync_resp.status_code, 200, sync_resp.text)

        patch_resp = self.client.patch(
            f"/api/v1/investment-journals/manual/{sync_resp.json()['item']['id']}",
            json={"raw_content": "should fail"},
        )
        self.assertEqual(patch_resp.status_code, 409, patch_resp.text)

    def test_journal_api_marks_snapshot_deleted_after_history_delete(self) -> None:
        history_id = self._seed_history()
        sync_resp = self.client.post(f"/api/v1/investment-journals/sync-analysis/{history_id}")
        entry_id = sync_resp.json()["item"]["id"]

        self.db.delete_analysis_history_records([history_id])

        get_resp = self.client.get(f"/api/v1/investment-journals/{entry_id}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        payload = get_resp.json()
        self.assertEqual(payload["source_status"], "deleted")
        self.assertFalse(payload["analysis_history_available"])
        self.assertIsNone(payload["analysis_history"])

    def test_ai_opinion_api_generate_and_regenerate(self) -> None:
        history_id = self._seed_history(code="AAPL")
        with patch("api.v1.endpoints.ai_opinions.AIOpinionGenerationService.generate") as mocked_generate:
            mocked_generate.return_value = {"ok": True}
            generate_resp = self.client.post(f"/api/v1/ai-opinions/generate/{history_id}")
            self.assertEqual(generate_resp.status_code, 202, generate_resp.text)
            payload = generate_resp.json()
            opinion_id = payload["opinion"]["id"]
            self.assertEqual(payload["opinion"]["generation_status"], "pending")

            for _ in range(50):
                task = get_task_queue().get_task(payload["task_id"])
                if task and task.status.value in {"completed", "failed"}:
                    break
                time.sleep(0.02)

            refreshed = self.client.get(f"/api/v1/ai-opinions/{opinion_id}")
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            self.assertEqual(refreshed.json()["generation_status"], "pending")
            self.assertEqual(refreshed.json()["retry_count"], 0)
            self.assertIn("output_json", refreshed.json())
            self.assertIn("error_message", refreshed.json())

            regenerate_resp = self.client.post(f"/api/v1/ai-opinions/{opinion_id}/regenerate")
            self.assertEqual(regenerate_resp.status_code, 409, regenerate_resp.text)

    def test_ai_opinion_api_lists_by_stock_code(self) -> None:
        first_history_id = self._seed_history(code="AAPL")
        second_history_id = self._seed_history(code="AAPL")
        other_history_id = self._seed_history(code="MSFT")
        service = AIOpinionService(db_manager=self.db)
        service.create_opinion(
            analysis_history_id=first_history_id,
            content="first AAPL recap",
            conclusion="first AAPL conclusion",
            output_json={"schema_version": "ai-opinion-output-v1", "summary": "first"},
        )
        service.create_opinion(
            analysis_history_id=second_history_id,
            content="second AAPL recap",
            conclusion="second AAPL conclusion",
            output_json={"schema_version": "ai-opinion-output-v1", "summary": "second"},
        )
        service.create_opinion(
            analysis_history_id=other_history_id,
            content="MSFT recap",
            conclusion="MSFT conclusion",
            output_json={"schema_version": "ai-opinion-output-v1", "summary": "other"},
        )

        list_resp = self.client.get(
            "/api/v1/ai-opinions",
            params={"stock_code": "aapl", "market": "us", "current_only": "false"},
        )

        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        payload = list_resp.json()
        self.assertEqual(payload["total"], 2)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["page_size"], 20)
        self.assertEqual(
            {item["analysis_history_id"] for item in payload["items"]},
            {first_history_id, second_history_id},
        )
        self.assertEqual({item["analysis_stock_code"] for item in payload["items"]}, {"AAPL"})
        self.assertTrue(all(item["analysis_created_at"] for item in payload["items"]))

    def test_ai_opinion_api_lists_by_stock_code_variants(self) -> None:
        history_id = self._seed_history(code="HK00700")
        service = AIOpinionService(db_manager=self.db)
        service.create_opinion(
            analysis_history_id=history_id,
            content="Tencent recap",
            conclusion="Tencent conclusion",
            output_json={"schema_version": "ai-opinion-output-v1", "summary": "hk"},
        )

        list_resp = self.client.get(
            "/api/v1/ai-opinions",
            params={"stock_code": "00700.HK", "market": "hk", "current_only": "false"},
        )

        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        payload = list_resp.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["analysis_history_id"], history_id)

    def test_ai_opinion_api_stores_feedback_with_optional_note(self) -> None:
        history_id = self._seed_history(code="AAPL")
        opinion = AIOpinionService(db_manager=self.db).create_opinion(
            analysis_history_id=history_id,
            content="AAPL recap",
            conclusion="AAPL conclusion",
            output_json={"schema_version": "ai-opinion-output-v1", "summary": "AAPL"},
        )

        response = self.client.put(
            f"/api/v1/ai-opinions/{opinion['id']}/feedback",
            json={"feedback_value": "useful", "feedback_note": "Useful risk framing."},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["feedback_value"], "useful")
        self.assertEqual(response.json()["feedback_note"], "Useful risk framing.")
        self.assertTrue(response.json()["feedback_updated_at"])

    def test_ai_opinion_api_paginates_stock_history(self) -> None:
        history_ids = [self._seed_history(code="AAPL") for _ in range(3)]
        service = AIOpinionService(db_manager=self.db)
        for index, history_id in enumerate(history_ids):
            service.create_opinion(
                analysis_history_id=history_id,
                content=f"AAPL recap {index}",
                conclusion=f"AAPL conclusion {index}",
                output_json={"schema_version": "ai-opinion-output-v1", "summary": str(index)},
            )

        first_page = self.client.get(
            "/api/v1/ai-opinions",
            params={"stock_code": "AAPL", "page": 1, "page_size": 2},
        )
        second_page = self.client.get(
            "/api/v1/ai-opinions",
            params={"stock_code": "AAPL", "page": 2, "page_size": 2},
        )

        self.assertEqual(first_page.status_code, 200, first_page.text)
        self.assertEqual(second_page.status_code, 200, second_page.text)
        self.assertEqual(first_page.json()["total"], 3)
        self.assertEqual(first_page.json()["page"], 1)
        self.assertEqual(first_page.json()["page_size"], 2)
        self.assertEqual(len(first_page.json()["items"]), 2)
        self.assertEqual(second_page.json()["total"], 3)
        self.assertEqual(second_page.json()["page"], 2)
        self.assertEqual(len(second_page.json()["items"]), 1)

    def test_journal_api_structure_and_retry(self) -> None:
        with patch(
            "api.v1.endpoints.investment_journals.InvestmentJournalStructuringService.structure"
        ) as mocked_structure:
            mocked_structure.return_value = {"ok": True}
            manual_resp = self.client.post(
                "/api/v1/investment-journals/manual",
                json={
                    "stock_code": "AAPL",
                    "market": "us",
                    "raw_content": "I may buy later if valuation improves.",
                },
            )
            self.assertEqual(manual_resp.status_code, 202, manual_resp.text)
            self.assertEqual(manual_resp.json()["entry"]["ai_processing_status"], "pending")
            entry_id = manual_resp.json()["entry"]["id"]

            with self.db.session_scope() as session:
                row = session.get(InvestmentJournalEntry, entry_id)
                row.ai_processing_status = "failed"

            retry_resp = self.client.post(f"/api/v1/investment-journals/{entry_id}/retry-structure")
            self.assertEqual(retry_resp.status_code, 202, retry_resp.text)
            self.assertEqual(retry_resp.json()["entry"]["id"], entry_id)

    def test_journal_api_structure_errors(self) -> None:
        not_found = self.client.post("/api/v1/investment-journals/999999/structure")
        self.assertEqual(not_found.status_code, 404, not_found.text)

        history_id = self._seed_history()
        analysis_entry = self.client.post(f"/api/v1/investment-journals/sync-analysis/{history_id}").json()["item"]
        analysis_conflict = self.client.post(f"/api/v1/investment-journals/{analysis_entry['id']}/structure")
        self.assertEqual(analysis_conflict.status_code, 409, analysis_conflict.text)

        with patch(
            "api.v1.endpoints.investment_journals.InvestmentJournalStructuringService.structure"
        ):
            manual_resp = self.client.post(
                "/api/v1/investment-journals/manual",
                json={
                    "stock_code": "AAPL",
                    "market": "us",
                    "raw_content": "seed",
                },
            )
            entry_id = manual_resp.json()["entry"]["id"]
            with self.db.session_scope() as session:
                row = session.get(InvestmentJournalEntry, entry_id)
                row.ai_processing_status = "failed"
                row.raw_content = None
            invalid = self.client.post(f"/api/v1/investment-journals/{entry_id}/structure")
            self.assertEqual(invalid.status_code, 422, invalid.text)

    def test_ai_opinion_api_returns_404_409_and_422(self) -> None:
        missing_history = self.client.post("/api/v1/ai-opinions/generate/999999")
        self.assertEqual(missing_history.status_code, 404, missing_history.text)

        invalid_history_id = self._seed_history(code="MSFT")
        with self.db.session_scope() as session:
            row = session.get(AnalysisHistory, invalid_history_id)
            row.analysis_summary = None
            row.raw_result = "{}"
        invalid_context = self.client.post(f"/api/v1/ai-opinions/generate/{invalid_history_id}")
        self.assertEqual(invalid_context.status_code, 422, invalid_context.text)

        history_id = self._seed_history(code="NVDA")
        with patch("api.v1.endpoints.ai_opinions.AIOpinionGenerationService.generate") as mocked_generate:
            mocked_generate.return_value = {"ok": True}
            first = self.client.post(f"/api/v1/ai-opinions/generate/{history_id}")
            self.assertEqual(first.status_code, 202, first.text)
            second = self.client.post(f"/api/v1/ai-opinions/generate/{history_id}")
            self.assertEqual(second.status_code, 409, second.text)


if __name__ == "__main__":
    unittest.main()
