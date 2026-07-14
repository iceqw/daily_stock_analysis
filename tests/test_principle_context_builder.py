# -*- coding: utf-8 -*-
"""Contract tests for the read-only M2-2 principle context builder."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import unicodedata
from types import SimpleNamespace

from src.config import Config
from src.repositories.investment_principle_repo import InvestmentPrincipleRepository
from src.services.investment_principle_service import InvestmentPrincipleService
from src.services.principle_context_builder import (
    PrincipleContextBuilder,
    PrincipleContextReadError,
    PrincipleContextValidationError,
)
from src.storage import DatabaseManager


class _FakeRepository:
    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error
        self.reads = 0
        self.writes = 0

    def list_active_current(self):
        self.reads += 1
        if self.error is not None:
            raise self.error
        return list(self.rows)


def _row(
    principle_id=1,
    version=1,
    *,
    status="active",
    current_version=None,
    category="risk_control",
    severity="advisory",
    scope_type="global",
    scope_market=None,
    scope_stock_code=None,
    title="A principle",
    statement="Keep risk bounded.",
    rationale=None,
):
    return SimpleNamespace(
        principle=SimpleNamespace(
            id=principle_id,
            status=status,
            current_version=version if current_version is None else current_version,
        ),
        version=SimpleNamespace(
            principle_id=principle_id,
            version=version,
            category=category,
            severity=severity,
            scope_type=scope_type,
            scope_market=scope_market,
            scope_stock_code=scope_stock_code,
            title=title,
            statement=statement,
            rationale=rationale,
        ),
    )


class PrincipleContextBuilderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        Config.reset_instance()
        DatabaseManager.reset_instance()
        self.db = DatabaseManager(db_url=f"sqlite:///{os.path.join(self.temp_dir.name, 'principles.db')}")
        self.repo = InvestmentPrincipleRepository(self.db)
        self.service = InvestmentPrincipleService(repo=self.repo, db_manager=self.db)

    def tearDown(self) -> None:
        self.db._engine.dispose(close=True)
        DatabaseManager.reset_instance()
        Config.reset_instance()
        self.temp_dir.cleanup()

    def _create_active(self, **fields):
        values = {
            "title": "Risk rule",
            "statement": "Keep risk bounded.",
            "rationale": "Protect capital.",
            "category": "risk_control",
            "severity": "advisory",
            "scope_type": "global",
        }
        values.update(fields)
        created = self.service.create_principle(**values)
        return self.service.activate_principle(created.principle.id)

    def test_only_active_principles_are_read(self):
        active = self._create_active(title="active")
        draft = self.service.create_principle(
            title="draft", statement="draft", category="risk", severity="soft"
        )
        archived = self._create_active(title="archived")
        self.service.archive_principle(archived.principle.id)
        rejected = self.service.create_principle(
            title="rejected", statement="rejected", category="risk", severity="soft"
        )
        self.service.reject_principle(rejected.principle.id)
        builder = PrincipleContextBuilder(repository=self.repo)
        result = builder.build()
        self.assertEqual([item.principle_id for item in result.items], [active.principle.id])
        self.assertNotEqual(draft.principle.id, active.principle.id)

    def test_only_current_version_is_used(self):
        created = self._create_active(title="v1")
        self.service.update_principle(
            created.principle.id,
            expected_current_version=1,
            fields={"title": "v2", "statement": "new statement"},
        )
        result = PrincipleContextBuilder(repository=self.repo).build()
        self.assertEqual(result.items[0].principle_version, 2)
        self.assertEqual(result.items[0].title, "v2")

    def test_scope_matching_and_global_retention(self):
        global_rule = self._create_active(title="global")
        market_rule = self._create_active(
            title="US market", scope_type="market", scope_market="us"
        )
        stock_rule = self._create_active(
            title="AAPL stock", scope_type="stock", scope_market="us", scope_stock_code="AAPL"
        )
        builder = PrincipleContextBuilder(repository=self.repo)
        result = builder.build(market="us", stock_code="AAPL")
        self.assertEqual(
            {item.principle_id for item in result.items},
            {global_rule.principle.id, market_rule.principle.id, stock_rule.principle.id},
        )

    def test_scope_mismatch_is_excluded(self):
        self._create_active(title="CN market", scope_type="market", scope_market="cn")
        self._create_active(title="AAPL", scope_type="stock", scope_market="us", scope_stock_code="AAPL")
        result = PrincipleContextBuilder(repository=self.repo).build(market="us", stock_code="MSFT")
        self.assertEqual(result.items, ())
        self.assertEqual(result.source_count, 2)
        self.assertFalse(result.truncated)

    def test_sorting_is_stable_and_prioritizes_known_severity(self):
        rows = [
            _row(3, category="z", severity="unknown"),
            _row(2, category="b", severity="soft"),
            _row(1, category="a", severity="hard"),
            _row(4, category="a", severity="advisory"),
        ]
        result = PrincipleContextBuilder(repository=_FakeRepository(rows)).build()
        self.assertEqual([item.principle_id for item in result.items], [1, 2, 4, 3])

    def test_input_order_does_not_change_snapshot(self):
        rows = [_row(1, category="b"), _row(2, category="a", severity="hard")]
        first = PrincipleContextBuilder(repository=_FakeRepository(rows)).build()
        second = PrincipleContextBuilder(repository=_FakeRepository(reversed(rows))).build()
        self.assertEqual(first.snapshot_json, second.snapshot_json)
        self.assertEqual(first.snapshot_hash, second.snapshot_hash)

    def test_nfc_and_newline_normalization(self):
        decomposed = "Cafe\u0301"
        row = _row(title=f"  {decomposed}\r\nRule  ", statement="  line1\rline2  ", rationale=None)
        item = PrincipleContextBuilder(repository=_FakeRepository([row])).build().items[0]
        self.assertEqual(item.title, "Café\nRule")
        self.assertEqual(item.statement, "line1\nline2")
        self.assertEqual(item.rationale, "")
        self.assertEqual(item.title, unicodedata.normalize("NFC", item.title))

    def test_content_hash_is_deterministic_and_changes_with_content(self):
        def build_item(row):
            return PrincipleContextBuilder(repository=_FakeRepository([row])).build().items[0]

        builder = build_item
        first = builder(_row(statement="same"))
        same = builder(_row(statement="same"))
        changed = builder(_row(statement="changed"))
        self.assertEqual(first.content_hash, same.content_hash)
        self.assertNotEqual(first.content_hash, changed.content_hash)

    def test_version_change_changes_snapshot_hash(self):
        first = PrincipleContextBuilder(repository=_FakeRepository([_row(version=1)])).build()
        second = PrincipleContextBuilder(repository=_FakeRepository([_row(version=2)])).build()
        self.assertNotEqual(first.snapshot_hash, second.snapshot_hash)

    def test_empty_principles_have_deterministic_empty_hash(self):
        result = PrincipleContextBuilder(repository=_FakeRepository()).build()
        self.assertEqual(result.items, ())
        self.assertEqual(result.snapshot_json, "[]")
        self.assertEqual(result.snapshot_hash, hashlib.sha256(b"[]").hexdigest())
        self.assertEqual(result.source_count, 0)
        self.assertEqual(result.retained_count, 0)
        self.assertEqual(result.truncated_count, 0)
        self.assertFalse(result.truncated)

    def test_limits_record_truncation_and_keep_stable_order(self):
        rows = [_row(idx, severity="hard", category=f"c{idx}") for idx in range(1, 5)]
        result = PrincipleContextBuilder(repository=_FakeRepository(rows), max_principles=2).build()
        self.assertEqual([item.principle_id for item in result.items], [1, 2])
        self.assertEqual(result.source_count, 4)
        self.assertEqual(result.retained_count, 2)
        self.assertEqual(result.truncated_count, 2)
        self.assertTrue(result.truncated)

    def test_text_limits_are_character_safe_and_hashed(self):
        result = PrincipleContextBuilder(
            repository=_FakeRepository([_row(statement="é" * 20, rationale="中" * 20)]),
            max_statement_chars=5,
            max_rationale_chars=4,
        ).build()
        self.assertEqual(len(result.items[0].statement), 5)
        self.assertEqual(len(result.items[0].rationale), 4)
        json.loads(result.snapshot_json)
        self.assertTrue(result.truncated)

    def test_current_version_mismatch_is_rejected(self):
        with self.assertRaises(PrincipleContextValidationError):
            PrincipleContextBuilder(repository=_FakeRepository([_row(version=1, current_version=2)])).build()

    def test_repository_current_version_pointer_failure_is_rejected(self):
        created = self._create_active()
        with self.db.session_scope() as session:
            principle = session.get(type(created.principle), created.principle.id)
            principle.current_version = 999
        with self.assertRaises(PrincipleContextValidationError):
            PrincipleContextBuilder(repository=self.repo).build()

    def test_invalid_identity_is_rejected(self):
        with self.assertRaises(PrincipleContextValidationError):
            PrincipleContextBuilder(repository=_FakeRepository([_row(principle_id=0)])).build()

    def test_duplicate_identity_is_rejected(self):
        with self.assertRaises(PrincipleContextValidationError):
            PrincipleContextBuilder(repository=_FakeRepository([_row(), _row()])).build()

    def test_repository_read_failure_is_not_empty_context(self):
        with self.assertRaises(PrincipleContextReadError):
            PrincipleContextBuilder(repository=_FakeRepository(error=RuntimeError("db down"))).build()

    def test_builder_does_not_write_database_or_call_generation(self):
        repository = _FakeRepository([_row()])
        result = PrincipleContextBuilder(repository=repository).build()
        self.assertEqual(repository.reads, 1)
        self.assertEqual(repository.writes, 0)
        self.assertNotIn("GenerationBackend", result.snapshot_json)

    def test_canonical_field_order_is_fixed(self):
        result = PrincipleContextBuilder(repository=_FakeRepository([_row()])).build()
        self.assertEqual(
            list(json.loads(result.snapshot_json)[0]),
            [
                "principle_id", "principle_version", "category", "severity", "scope",
                "title", "statement", "rationale", "content_hash",
            ],
        )

    def test_snapshot_is_deeply_immutable(self):
        result = PrincipleContextBuilder(repository=_FakeRepository([_row()])).build()
        with self.assertRaises(AttributeError):
            result.items.append(result.items[0])
        with self.assertRaises((AttributeError, TypeError)):
            result.items = ()
        with self.assertRaises((AttributeError, TypeError)):
            result.items[0].scope.market = "cn"

        original_json = result.snapshot_json
        original_hash = result.snapshot_hash
        payload = result.to_dict()
        payload["items"].append(payload["items"][0])
        payload["items"][0]["scope"]["market"] = "cn"
        self.assertEqual(result.snapshot_json, original_json)
        self.assertEqual(result.snapshot_hash, original_hash)
        self.assertEqual(len(result.items), 1)

    def test_total_budget_keeps_only_sorted_prefix(self):
        rows = [
            _row(3, severity="soft", title="soft", statement="s"),
            _row(2, severity="hard", title="hard-large", statement="xxxxxxxxxxxx"),
            _row(1, severity="hard", title="hard", statement="h"),
        ]
        first = PrincipleContextBuilder(
            repository=_FakeRepository(rows), max_total_chars=8
        ).build()
        second = PrincipleContextBuilder(
            repository=_FakeRepository(reversed(rows)), max_total_chars=8
        ).build()
        self.assertEqual([item.principle_id for item in first.items], [1])
        self.assertEqual(first.items, second.items)
        self.assertEqual(first.truncated_count, 2)
        self.assertTrue(first.truncated)


if __name__ == "__main__":
    unittest.main()
