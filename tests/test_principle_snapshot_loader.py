import hashlib
import json
import unittest
from types import SimpleNamespace

from src.services.principle_context_builder import (
    PrincipleContextBuilder,
    PrincipleContextValidationError,
    load_frozen_principle_snapshot,
)


class _Repo:
    def __init__(self, rows):
        self.rows = rows

    def list_active_current(self):
        return self.rows


def _row():
    return SimpleNamespace(
        principle=SimpleNamespace(id=1, status="active", current_version=1),
        version=SimpleNamespace(
            principle_id=1, version=1, category="risk", severity="hard", scope_type="global",
            scope_market=None, scope_stock_code=None, title="Evidence", statement="Use evidence", rationale="Reason",
        ),
    )


def _row_without_rationale():
    row = _row()
    row.version.rationale = None
    return row


class FrozenSnapshotLoaderTest(unittest.TestCase):
    def test_empty_rationale_is_normalized_and_restored(self):
        snapshot = PrincipleContextBuilder(repository=_Repo([_row_without_rationale()])).build()

        self.assertEqual(snapshot.items[0].rationale, "")
        restored = load_frozen_principle_snapshot(
            snapshot.snapshot_json, snapshot.snapshot_hash, snapshot.retained_count
        )

        self.assertEqual(restored.items[0].rationale, "")
        self.assertEqual(restored.snapshot_hash, snapshot.snapshot_hash)

    def test_restore_and_empty_snapshot(self):
        snapshot = PrincipleContextBuilder(repository=_Repo([_row()])).build()
        restored = load_frozen_principle_snapshot(snapshot.snapshot_json, snapshot.snapshot_hash, snapshot.retained_count)
        self.assertEqual(restored.snapshot_hash, snapshot.snapshot_hash)
        empty = load_frozen_principle_snapshot("[]", hashlib.sha256(b"[]").hexdigest(), 0)
        self.assertEqual(empty.items, ())

    def test_tampering_hash_count_and_content_is_rejected(self):
        snapshot = PrincipleContextBuilder(repository=_Repo([_row()])).build()
        payload = json.loads(snapshot.snapshot_json)
        payload[0]["statement"] = "changed"
        modified = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.assertRaises(PrincipleContextValidationError):
            load_frozen_principle_snapshot(modified, snapshot.snapshot_hash, 1)
        with self.assertRaises(PrincipleContextValidationError):
            load_frozen_principle_snapshot(snapshot.snapshot_json, "0" * 64, 1)
        with self.assertRaises(PrincipleContextValidationError):
            load_frozen_principle_snapshot(snapshot.snapshot_json, snapshot.snapshot_hash, 2)
