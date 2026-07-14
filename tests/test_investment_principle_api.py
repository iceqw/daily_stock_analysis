# -*- coding: utf-8 -*-
"""API contract tests for investment principles."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from src.config import Config
from src.storage import DatabaseManager


@pytest.fixture()
def api_client(tmp_path: Path):
    env_names = ("DATABASE_PATH", "STOCK_INDEX_REMOTE_UPDATE_ENABLED", "DSA_RUNTIME_SCHEDULER_SUPPRESS_START")
    old_env = {name: os.environ.get(name) for name in env_names}
    db_path = tmp_path / "principles-api.db"
    os.environ["DATABASE_PATH"] = str(db_path)
    os.environ["STOCK_INDEX_REMOTE_UPDATE_ENABLED"] = "false"
    os.environ["DSA_RUNTIME_SCHEDULER_SUPPRESS_START"] = "true"
    Config.reset_instance()
    DatabaseManager.reset_instance()
    manager = DatabaseManager(f"sqlite:///{db_path}")
    app = create_app(static_dir=tmp_path / "static", db_manager=manager)
    client = TestClient(app)
    with client:
        yield client
    DatabaseManager.reset_instance()
    Config.reset_instance()
    for name, value in old_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _create(client: TestClient, **overrides):
    payload = {
        "title": "Long-term discipline",
        "statement": "Do not change long-term logic because of short-term price movement.",
        "rationale": "Avoid emotional decisions.",
        "category": "discipline",
        "severity": "soft",
        "scope_type": "global",
        "sources": [{"source_type": "manual", "source_excerpt": "Keep the thesis stable."}],
    }
    payload.update(overrides)
    return client.post("/api/v1/investment-principles", json=payload)


def test_router_and_create_contract(api_client: TestClient):
    response = _create(api_client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["principle"]["status"] == "draft"
    assert body["principle"]["current_version"] == 1
    assert body["current_version"]["source_count"] == 1
    assert body["sources"][0]["source_status"] == "available"
    assert "_sa_instance_state" not in response.text
    openapi = api_client.get("/openapi.json").json()
    assert "/api/v1/investment-principles" in openapi["paths"]
    assert "/api/v1/investment-principles/{principle_id}/versions" in openapi["paths"]
    assert api_client.delete("/api/v1/investment-principles/1").status_code == 405
    assert api_client.post("/api/v1/investment-principles/extract").status_code in {404, 405}


def test_create_validation_and_status_is_not_accepted(api_client: TestClient):
    assert _create(api_client, title="").status_code == 422
    assert _create(api_client, severity="invalid").status_code == 422
    assert _create(api_client, scope_type="global", scope_market="cn").status_code == 400
    response = _create(api_client, status="active")
    assert response.status_code == 201
    assert response.json()["principle"]["status"] == "draft"


def test_patch_unset_null_sources_only_and_stale_version(api_client: TestClient):
    created = _create(api_client).json()
    principle_id = created["principle"]["id"]
    updated = api_client.patch(
        f"/api/v1/investment-principles/{principle_id}",
        json={"expected_current_version": 1, "rationale": None},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["current_version"]["version"] == 2
    assert updated.json()["current_version"]["rationale"] is None
    unchanged = api_client.patch(
        f"/api/v1/investment-principles/{principle_id}",
        json={"expected_current_version": 2},
    )
    assert unchanged.status_code == 400
    source_only = api_client.patch(
        f"/api/v1/investment-principles/{principle_id}",
        json={"expected_current_version": 2, "sources": [{"source_type": "manual", "source_excerpt": "More evidence."}]},
    )
    assert source_only.status_code == 200
    assert source_only.json()["principle"]["current_version"] == 2
    stale = api_client.patch(
        f"/api/v1/investment-principles/{principle_id}",
        json={"expected_current_version": 1, "title": "Concurrent edit"},
    )
    assert stale.status_code == 409


def test_list_filters_versions_and_status_actions(api_client: TestClient):
    first = _create(api_client, category="discipline").json()["principle"]["id"]
    second = _create(api_client, category="valuation").json()["principle"]["id"]
    listed = api_client.get("/api/v1/investment-principles", params={"category": "discipline"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["source_count"] == 1
    assert api_client.get("/api/v1/investment-principles", params={"page": 0}).status_code == 400
    assert api_client.get("/api/v1/investment-principles", params={"page_size": 101}).status_code == 400
    assert api_client.get("/api/v1/investment-principles", params={"sort_by": "bad"}).status_code == 400

    assert api_client.post(f"/api/v1/investment-principles/{first}/activate", json={"expected_status": "draft"}).status_code == 200
    assert api_client.post(f"/api/v1/investment-principles/{first}/archive", json={"expected_status": "active"}).status_code == 200
    assert api_client.post(f"/api/v1/investment-principles/{first}/activate", json={"expected_status": "archived"}).status_code == 200
    assert api_client.post(f"/api/v1/investment-principles/{first}/reject", json={"expected_status": "active"}).status_code == 409
    assert api_client.post(f"/api/v1/investment-principles/{first}/activate", json={"expected_status": "draft"}).status_code == 409
    assert api_client.post(f"/api/v1/investment-principles/{second}/reject", json={"expected_status": "draft"}).status_code == 200
    assert api_client.post(f"/api/v1/investment-principles/{second}/restore-draft", json={"expected_status": "rejected"}).status_code == 200
    versions = api_client.get(f"/api/v1/investment-principles/{first}/versions")
    assert versions.status_code == 200
    assert versions.json()["items"][0]["version"] == 1


def test_not_found_and_unexpected_service_error_mapping(api_client: TestClient):
    missing = api_client.get("/api/v1/investment-principles/999999")
    assert missing.status_code == 404
    assert missing.json()["error"] == "not_found"
