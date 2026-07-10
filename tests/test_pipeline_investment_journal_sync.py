# -*- coding: utf-8 -*-
"""Pipeline guard tests for best-effort journal sync."""

from __future__ import annotations

import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock, patch

if "dotenv" not in sys.modules:
    dotenv_stub = ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
    sys.modules["dotenv"] = dotenv_stub

try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    sys.modules["litellm"] = MagicMock()

from src.core.pipeline import StockAnalysisPipeline


class PipelineInvestmentJournalSyncTestCase(unittest.TestCase):
    def test_helper_swallow_sync_failures(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.db = object()

        with patch(
            "src.services.investment_journal_service.InvestmentJournalService.sync_analysis_entry",
            side_effect=RuntimeError("boom"),
        ):
            pipeline._sync_investment_journal_after_history_save(
                query_id="q-1",
                source_report_id=123,
                stock_code="600519",
            )

    def test_helper_calls_sync_for_supported_records(self) -> None:
        pipeline = StockAnalysisPipeline.__new__(StockAnalysisPipeline)
        pipeline.db = object()

        with patch(
            "src.services.investment_journal_service.InvestmentJournalService.sync_analysis_entry",
            return_value={"created": True},
        ) as sync_mock:
            pipeline._sync_investment_journal_after_history_save(
                query_id="q-2",
                source_report_id=456,
                stock_code="AAPL",
            )

        sync_mock.assert_called_once_with(456)


if __name__ == "__main__":
    unittest.main()
