# -*- coding: utf-8 -*-
"""Pydantic schemas for AI opinion APIs."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


OpinionGenerationStatus = Literal["pending", "generating", "completed", "failed", "rejected"]
OpinionSourceStatus = Literal["available", "deleted"]
OpinionFeedbackValue = Literal["useful", "not_useful"]


class AIOpinionGenerateAccepted(BaseModel):
    opinion: "AIOpinionItem"
    accepted: bool = True
    task_id: str
    trace_id: str
    task_status: str
    message: Optional[str] = None


class AIOpinionItem(BaseModel):
    """Serialized AI opinion record."""

    id: int
    analysis_history_id: Optional[int] = None
    analysis_history_available: bool
    version: int
    is_current: bool
    generation_status: OpinionGenerationStatus
    source_status: OpinionSourceStatus
    title: Optional[str] = None
    content: Optional[str] = None
    conclusion: Optional[str] = None
    output_json: Optional[Any] = None
    evidence: Optional[Any] = None
    risks: Optional[Any] = None
    limitations: Optional[Any] = None
    watch_items: Optional[Any] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    temperature: Optional[float] = None
    prompt_version: Optional[str] = None
    audit_metadata: Optional[Any] = None
    error_message: Optional[str] = None
    context_hash: Optional[str] = None
    principle_snapshot_hash: Optional[str] = None
    principle_snapshot_count: Optional[int] = None
    principle_snapshot_json: Optional[Any] = None
    principle_refs: List[Any] = Field(default_factory=list)
    retry_count: int = 0
    generated_at: Optional[str] = None
    feedback_value: Optional[OpinionFeedbackValue] = None
    feedback_note: Optional[str] = None
    feedback_updated_at: Optional[str] = None
    analysis_stock_code: Optional[str] = None
    analysis_stock_name: Optional[str] = None
    analysis_created_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AIOpinionListResponse(BaseModel):
    """List response for AI opinions."""

    items: List[AIOpinionItem] = Field(default_factory=list)
    total: int
    page: int = 1
    page_size: int = 50
    stats: Optional[dict[str, int]] = None


class AIOpinionFeedbackRequest(BaseModel):
    feedback_value: OpinionFeedbackValue
    feedback_note: Optional[str] = Field(default=None, max_length=1000)
