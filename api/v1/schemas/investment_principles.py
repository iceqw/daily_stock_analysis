# -*- coding: utf-8 -*-
"""Pydantic v2 contracts for investment principle APIs."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


PrincipleStatus = Literal["draft", "active", "archived", "rejected"]
PrincipleSeverity = Literal["hard", "soft", "advisory"]
PrincipleScopeType = Literal["global", "market", "stock"]
PrincipleSourceType = Literal["manual", "journal", "opinion"]
PrincipleSourceStatus = Literal["available", "deleted", "unavailable"]
PrincipleSortBy = Literal["updated_at", "created_at", "title", "status"]
SortOrder = Literal["asc", "desc"]


class InvestmentPrincipleSourceCreate(BaseModel):
    source_type: PrincipleSourceType
    source_id: Optional[int] = Field(default=None, gt=0)
    source_excerpt: Optional[str] = Field(default=None, max_length=4000)


class InvestmentPrincipleCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    statement: str = Field(..., min_length=1, max_length=20000)
    rationale: Optional[str] = Field(default=None, max_length=20000)
    category: str = Field(..., min_length=1, max_length=64)
    severity: PrincipleSeverity = "advisory"
    scope_type: PrincipleScopeType = "global"
    scope_market: Optional[str] = Field(default=None, min_length=2, max_length=8)
    scope_stock_code: Optional[str] = Field(default=None, min_length=1, max_length=32)
    change_note: Optional[str] = Field(default=None, max_length=4000)
    sources: List[InvestmentPrincipleSourceCreate] = Field(default_factory=list)


class InvestmentPrincipleUpdateRequest(BaseModel):
    expected_current_version: int = Field(..., gt=0)
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    statement: Optional[str] = Field(default=None, min_length=1, max_length=20000)
    rationale: Optional[str] = Field(default=None, max_length=20000)
    category: Optional[str] = Field(default=None, min_length=1, max_length=64)
    severity: Optional[PrincipleSeverity] = None
    scope_type: Optional[PrincipleScopeType] = None
    scope_market: Optional[str] = Field(default=None, min_length=2, max_length=8)
    scope_stock_code: Optional[str] = Field(default=None, min_length=1, max_length=32)
    change_note: Optional[str] = Field(default=None, max_length=4000)
    sources: Optional[List[InvestmentPrincipleSourceCreate]] = None


class InvestmentPrincipleStatusActionRequest(BaseModel):
    expected_status: PrincipleStatus


class InvestmentPrincipleSourceResponse(BaseModel):
    id: int
    principle_version_id: int
    source_type: PrincipleSourceType
    source_id: Optional[int] = None
    source_excerpt: Optional[str] = None
    source_status: PrincipleSourceStatus
    created_at: datetime
    updated_at: datetime


class InvestmentPrincipleVersionResponse(BaseModel):
    id: int
    principle_id: int
    version: int
    title: str
    statement: str
    rationale: Optional[str] = None
    category: str
    severity: PrincipleSeverity
    scope_type: PrincipleScopeType
    scope_market: Optional[str] = None
    scope_stock_code: Optional[str] = None
    change_note: Optional[str] = None
    created_at: datetime
    source_count: int = 0
    sources: Optional[List[InvestmentPrincipleSourceResponse]] = None


class InvestmentPrincipleResponse(BaseModel):
    id: int
    status: PrincipleStatus
    current_version: int
    created_at: datetime
    updated_at: datetime
    status_changed_at: datetime
    activated_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None


class InvestmentPrincipleDetailResponse(BaseModel):
    principle: InvestmentPrincipleResponse
    current_version: InvestmentPrincipleVersionResponse
    sources: List[InvestmentPrincipleSourceResponse] = Field(default_factory=list)


class InvestmentPrincipleListItemResponse(BaseModel):
    principle: InvestmentPrincipleResponse
    current_version: InvestmentPrincipleVersionResponse
    source_count: int


class InvestmentPrincipleListResponse(BaseModel):
    items: List[InvestmentPrincipleListItemResponse] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class InvestmentPrincipleVersionListResponse(BaseModel):
    items: List[InvestmentPrincipleVersionResponse] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
