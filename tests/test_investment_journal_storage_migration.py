# -*- coding: utf-8 -*-
"""Compatibility tests for stage 1 storage bootstrap."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from types import ModuleType

if "dotenv" not in sys.modules:
    dotenv_stub = ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *args, **kwargs: None
    dotenv_stub.dotenv_values = lambda *args, **kwargs: {}
    sys.modules["dotenv"] = dotenv_stub

from src.config import Config
from src.storage import DatabaseManager


class InvestmentJournalStorageMigrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._old_database_path = os.environ.get("DATABASE_PATH")
        self._db_path = os.path.join(self._temp_dir.name, "legacy_stage1.db")
        os.environ["DATABASE_PATH"] = self._db_path
        self._create_legacy_database()

    def tearDown(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        if self._old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old_database_path
        self._temp_dir.cleanup()

    def _create_legacy_database(self) -> None:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                """
                CREATE TABLE analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_id VARCHAR(100),
                    code VARCHAR(20),
                    name VARCHAR(100),
                    report_type VARCHAR(20),
                    analysis_summary TEXT,
                    raw_result TEXT,
                    created_at DATETIME
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE investment_journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code VARCHAR(16) NOT NULL,
                    market VARCHAR(8) NOT NULL,
                    entry_type VARCHAR(16) NOT NULL,
                    source_analysis_history_id INTEGER UNIQUE,
                    raw_content TEXT,
                    summary_snapshot TEXT,
                    risk_summary TEXT,
                    watch_items_json TEXT,
                    source_label VARCHAR(64) NOT NULL DEFAULT 'manual',
                    structured_output_json TEXT,
                    ai_processing_status VARCHAR(24) NOT NULL DEFAULT 'not_applicable',
                    model VARCHAR(128),
                    prompt_version VARCHAR(64),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE ai_opinions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_history_id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    is_current BOOLEAN NOT NULL DEFAULT 1,
                    generation_status VARCHAR(24) NOT NULL DEFAULT 'pending',
                    conclusion TEXT,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            conn.execute(
                """
                INSERT INTO analysis_history (
                    id, query_id, code, name, report_type, analysis_summary, raw_result, created_at
                ) VALUES (1, 'legacy-q1', '600519', 'Mock Stock', 'stock', 'legacy summary', '{}', '2026-07-10 08:00:00')
                """
            )
            conn.execute(
                """
                INSERT INTO investment_journal_entries (
                    stock_code, market, entry_type, source_analysis_history_id,
                    summary_snapshot, source_label, ai_processing_status, created_at, updated_at
                ) VALUES (
                    '600519', 'cn', 'analysis', 1,
                    'legacy snapshot', 'analysis_history', 'not_applicable', '2026-07-10 08:00:00', '2026-07-10 08:00:00'
                )
                """
            )
            conn.execute(
                """
                INSERT INTO ai_opinions (
                    analysis_history_id, version, is_current, generation_status, conclusion, created_at, updated_at
                ) VALUES
                    (1, 1, 1, 'succeeded', 'legacy current v1', '2026-07-10 08:00:00', '2026-07-10 08:00:00'),
                    (1, 2, 1, 'succeeded', 'legacy current v2', '2026-07-10 08:05:00', '2026-07-10 08:05:00')
                """
            )
            conn.commit()
        finally:
            conn.close()

    def test_bootstrap_adds_stage1_tables_and_indexes_without_rebuild(self) -> None:
        Config.reset_instance()
        DatabaseManager.reset_instance()
        manager = DatabaseManager.get_instance()

        conn = sqlite3.connect(self._db_path)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("analysis_history", tables)
            self.assertIn("investment_journal_entries", tables)
            self.assertIn("ai_opinions", tables)

            journal_columns = {
                row[1]: row
                for row in conn.execute("PRAGMA table_info(investment_journal_entries)")
            }
            self.assertIn("source_status", journal_columns)
            self.assertIn("provider", journal_columns)
            self.assertIn("temperature", journal_columns)
            self.assertIn("structured_version", journal_columns)
            self.assertIn("structured_at", journal_columns)
            self.assertIn("structured_error", journal_columns)
            self.assertIn("structuring_attempt", journal_columns)
            self.assertIn("structuring_requested_at", journal_columns)

            journal_row = conn.execute(
                """
                SELECT summary_snapshot, source_analysis_history_id, source_status
                FROM investment_journal_entries
                WHERE stock_code = '600519'
                """
            ).fetchone()
            self.assertEqual(journal_row, ("legacy snapshot", 1, "available"))

            ai_indexes = {
                row[1] for row in conn.execute("PRAGMA index_list('ai_opinions')")
            }
            self.assertIn("uix_ai_opinion_current_per_analysis", ai_indexes)

            current_rows = conn.execute(
                """
                SELECT version, is_current
                FROM ai_opinions
                WHERE analysis_history_id = 1
                ORDER BY version ASC
                """
            ).fetchall()
            self.assertEqual(current_rows, [(1, 0), (2, 1)])
        finally:
            conn.close()

        raw_conn = manager._engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            try:
                self.assertEqual(cursor.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            finally:
                cursor.close()
        finally:
            raw_conn.close()


if __name__ == "__main__":
    unittest.main()
