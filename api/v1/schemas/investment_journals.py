# -*- coding: utf-8 -*-
"""Pydantic schemas for investment journal APIs."""

from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class JournalAnalysisHistoryRef(BaseModel):
    """Minimal linked analysis_history reference."""

    id: int
    query_id: Optional[str] = None
    report_type: Optional[str] = None
    created_at: Optional[str] = None


class JournalCurrentAIOpinionRef(BaseModel):
    """Current AI opinion summary attached to an analysis journal entry."""

    id: int
    analysis_history_id: int
    version: int
    generation_status: Literal["pending", "generating", "completed", "failed", "rejected"]
    conclusion: Optional[str] = None
    created_at: Optional[str] = None


class InvestmentJournalEntryItem(BaseModel):
    """Serialized investment journal timeline item."""

    id: int
    stock_code: str
    market: str
    entry_type: Literal["analysis", "manual"]
    source_analysis_history_id: Optional[int] = None
    source_status: Literal["available", "deleted"]
    raw_content: Optional[str] = None
    summary_snapshot: Optional[str] = None
    risk_summary: Optional[str] = None
    watch_items: Optional[Any] = None
    source_label: str
    structured_output: Optional[Any] = None
    ai_processing_status: Literal["not_applicable", "pending", "processing", "completed", "failed"]
    model: Optional[str] = None
    provider: Optional[str] = None
    temperature: Optional[float] = None
    prompt_version: Optional[str] = None
    structured_version: Optional[str] = None
    structured_at: Optional[str] = None
    structured_error: Optional[str] = None
    analysis_history: Optional[JournalAnalysisHistoryRef] = None
    analysis_history_available: bool
    current_ai_opinion: Optional[JournalCurrentAIOpinionRef] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class InvestmentJournalListResponse(BaseModel):
    """Paginated journal entry list."""

    items: List[InvestmentJournalEntryItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class ManualJournalEntryCreateRequest(BaseModel):
    """Create a manual investment note."""

    stock_code: str = Field(..., min_length=1, max_length=32)
    market: str = Field(..., min_length=2, max_length=8)
    raw_content: str = Field(..., min_length=1, max_length=20000)
    summary_snapshot: Optional[str] = Field(default=None, max_length=4000)


class ManualJournalEntryUpdateRequest(BaseModel):
    """Update a manual investment note."""

    raw_content: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    summary_snapshot: Optional[str] = Field(default=None, max_length=4000)


class AnalysisJournalSyncResponse(BaseModel):
    """Response for idempotent analysis->journal sync."""

    item: InvestmentJournalEntryItem
    created: bool


class InvestmentJournalStructuringAccepted(BaseModel):
    entry: InvestmentJournalEntryItem
    accepted: bool = True
    task_id: str
    trace_id: str
    task_status: str
    message: Optional[str] = None
