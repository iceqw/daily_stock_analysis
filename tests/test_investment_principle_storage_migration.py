# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from datetime import date

from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from src.config import Config
from src.storage import (
    DatabaseManager,
    DatabaseSchemaMigration,
    CURRENT_SCHEMA_VERSION,
    InvestmentPrinciple,
    InvestmentPrincipleSource,
    InvestmentPrincipleVersion,
    StockDaily,
)


class TestInvestmentPrincipleStorageMigration(unittest.TestCase):
    def setUp(self) -> None:
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "investment_principles.db")

    def tearDown(self) -> None:
        instance = DatabaseManager._instance
        if instance is not None and getattr(instance, "_engine", None) is not None:
            instance._engine.dispose(close=True)
            instance._engine.pool.dispose()
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.temp_dir.cleanup()

    def _new_db(self) -> DatabaseManager:
        return DatabaseManager(db_url=f"sqlite:///{self.db_path}")

    @staticmethod
    def _index_names(db: DatabaseManager, table_name: str) -> set[str]:
        with db._engine.connect() as connection:
            return {
                row[1]
                for row in connection.execute(text(f"PRAGMA index_list({table_name})")).fetchall()
            }

    def test_new_database_creates_schema_marker_tables_indexes_and_foreign_keys(self) -> None:
        db = self._new_db()
        inspector = inspect(db._engine)

        self.assertTrue(
            {
                "investment_principles",
                "investment_principle_versions",
                "investment_principle_sources",
            }.issubset(set(inspector.get_table_names()))
        )
        self.assertTrue(
            {
                "status",
                "current_version",
                "status_changed_at",
                "activated_at",
                "archived_at",
                "rejected_at",
            }.issubset({column["name"] for column in inspector.get_columns("investment_principles")})
        )
        self.assertTrue(
            {
                "principle_id",
                "version",
                "title",
                "statement",
                "scope_type",
                "scope_market",
                "scope_stock_code",
            }.issubset({column["name"] for column in inspector.get_columns("investment_principle_versions")})
        )
        self.assertTrue(
            {
                "principle_version_id",
                "source_type",
                "source_id",
                "source_excerpt",
                "source_status",
            }.issubset({column["name"] for column in inspector.get_columns("investment_principle_sources")})
        )

        with db.get_session() as session:
            marker = session.get(DatabaseSchemaMigration, CURRENT_SCHEMA_VERSION)
            marker_versions = {
                row.version for row in session.query(DatabaseSchemaMigration).all()
            }
        self.assertIsNotNone(marker)
        self.assertEqual(marker_versions, {CURRENT_SCHEMA_VERSION})

        self.assertIn("ix_investment_principle_status_updated", self._index_names(db, "investment_principles"))
        self.assertIn("ix_investment_principle_version_scope", self._index_names(db, "investment_principle_versions"))
        self.assertIn("ix_investment_principle_source_version_status", self._index_names(db, "investment_principle_sources"))

        with db._engine.connect() as connection:
            self.assertEqual(connection.execute(text("PRAGMA foreign_keys")).fetchone()[0], 1)

    def test_phase9_style_database_is_upgraded_without_changing_existing_data(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE schema_migrations (
                    version VARCHAR(64) PRIMARY KEY,
                    description VARCHAR(255) NOT NULL,
                    applied_at DATETIME NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                ("2026-06-05-create-all-baseline", "legacy baseline", "2026-06-05 00:00:00"),
            )
            connection.execute(
                """
                CREATE TABLE stock_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code VARCHAR(10) NOT NULL,
                    date DATE NOT NULL,
                    open FLOAT,
                    high FLOAT,
                    low FLOAT,
                    close FLOAT
                    ,volume FLOAT,
                    amount FLOAT,
                    pct_chg FLOAT,
                    ma5 FLOAT,
                    ma10 FLOAT,
                    ma20 FLOAT,
                    volume_ratio FLOAT,
                    data_source VARCHAR(50),
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
            connection.execute(
                "INSERT INTO stock_daily (code, date, close) VALUES (?, ?, ?)",
                ("600519", date(2026, 7, 13).isoformat(), 1500.0),
            )
            connection.commit()

        db = self._new_db()
        with db.get_session() as session:
            row = session.execute(select(StockDaily).where(StockDaily.code == "600519")).scalar_one()
            self.assertEqual(row.close, 1500.0)
            self.assertIsNotNone(session.get(DatabaseSchemaMigration, CURRENT_SCHEMA_VERSION))
            self.assertIsNotNone(session.get(DatabaseSchemaMigration, "2026-06-05-create-all-baseline"))

    def test_initialization_is_idempotent_and_marker_is_not_duplicated(self) -> None:
        db = self._new_db()
        db._ensure_schema_migration_record()
        db._ensure_schema_migration_record()
        db.reset_instance()

        db = DatabaseManager(db_url=f"sqlite:///{self.db_path}")
        with db.get_session() as session:
            count = session.query(DatabaseSchemaMigration).filter_by(
                version=CURRENT_SCHEMA_VERSION
            ).count()
        self.assertEqual(count, 1)

    def test_unique_version_and_check_constraints_are_enforced(self) -> None:
        db = self._new_db()
        with db.get_session() as session:
            principle = InvestmentPrinciple()
            session.add(principle)
            session.flush()
            principle_id = principle.id
            session.add(
                InvestmentPrincipleVersion(
                    principle_id=principle_id,
                    version=1,
                    title="Title",
                    statement="Statement",
                    category="risk",
                    severity="hard",
                    scope_type="global",
                )
            )
            session.commit()

        with self.assertRaises(IntegrityError):
            with db.get_session() as session:
                session.add(
                    InvestmentPrincipleVersion(
                        principle_id=principle_id,
                        version=1,
                        title="Duplicate",
                        statement="Duplicate",
                        category="risk",
                        severity="hard",
                        scope_type="global",
                    )
                )
                session.commit()

        invalid_versions = [
            {"version": 0, "severity": "hard", "scope_type": "global"},
            {"version": 2, "severity": "invalid", "scope_type": "global"},
            {"version": 2, "severity": "hard", "scope_type": "global", "scope_market": "cn"},
            {"version": 2, "severity": "hard", "scope_type": "market"},
            {"version": 2, "severity": "hard", "scope_type": "stock", "scope_market": "cn"},
        ]
        for values in invalid_versions:
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with db.get_session() as session:
                    session.add(
                        InvestmentPrincipleVersion(
                            principle_id=principle_id,
                            title="Invalid",
                            statement="Invalid",
                            category="risk",
                            **values,
                        )
                    )
                    session.commit()

    def test_source_checks_and_restrict_foreign_keys_are_enforced(self) -> None:
        db = self._new_db()
        with db.get_session() as session:
            principle = InvestmentPrinciple()
            session.add(principle)
            session.flush()
            version = InvestmentPrincipleVersion(
                principle_id=principle.id,
                version=1,
                title="Title",
                statement="Statement",
                category="risk",
                severity="advisory",
                scope_type="global",
            )
            session.add(version)
            session.flush()
            version_id = version.id
            session.add(
                InvestmentPrincipleSource(
                    principle_version_id=version_id,
                    source_type="manual",
                    source_status="available",
                )
            )
            session.commit()

        invalid_sources = [
            {"source_type": "external", "source_id": "1"},
            {"source_type": "journal"},
            {"source_type": "opinion", "source_id": ""},
            {"source_type": "manual", "source_status": "invalid"},
        ]
        for values in invalid_sources:
            with self.subTest(values=values), self.assertRaises(IntegrityError):
                with db.get_session() as session:
                    session.add(
                        InvestmentPrincipleSource(
                            principle_version_id=version_id,
                            **values,
                        )
                    )
                    session.commit()

        with self.assertRaises(IntegrityError):
            with db.get_session() as session:
                session.add(
                    InvestmentPrincipleSource(
                        principle_version_id=999999,
                        source_type="manual",
                    )
                )
                session.commit()

        with self.assertRaises(IntegrityError):
            with db.get_session() as session:
                session.delete(version)
                session.commit()

        with self.assertRaises(IntegrityError):
            with db.get_session() as session:
                session.delete(principle)
                session.commit()


if __name__ == "__main__":
    unittest.main()
