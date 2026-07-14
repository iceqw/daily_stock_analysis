# -*- coding: utf-8 -*-
"""Schema parsing and safety validation for structured investment journal output."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.services.investment_journal_context_builder import JournalStructuringContext


class InvestmentJournalSchemaError(ValueError):
    """Raised when journal structuring output is invalid JSON or schema."""


class InvestmentJournalSafetyError(ValueError):
    """Raised when journal structuring output crosses product safety boundaries."""


class StructuredInvestmentJournalOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["investment-journal-structured-v1"]
    summary: str = Field(..., min_length=1, max_length=1000)
    journal_type: Literal[
        "thesis_note",
        "post_mortem",
        "watchlist_note",
        "observation",
        "research_note",
        "emotion_review",
        "other",
    ]
    investment_thesis: Optional[str] = Field(default=None, max_length=1200)
    reasons: List[str] = Field(default_factory=list, max_length=10)
    risks: List[str] = Field(default_factory=list, max_length=10)
    assumptions: List[str] = Field(default_factory=list, max_length=10)
    invalidation_conditions: List[str] = Field(default_factory=list, max_length=10)
    emotions: List[str] = Field(default_factory=list, max_length=8)
    cognitive_bias: List[str] = Field(default_factory=list, max_length=8)
    follow_up_items: List[str] = Field(default_factory=list, max_length=10)
    tags: List[str] = Field(default_factory=list, max_length=12)


_ADVICE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"建议\s*(买入|卖出|加仓|减仓)",
        r"(当前|现在|此时).{0,6}(应该|应当).{0,6}(买入|卖出|加仓|减仓)",
        r"\b(should|recommend|recommended|now is the time to)\s+(buy|sell)\b",
    )
]
_ATTRIBUTION_MARKERS = ("用户", "原文", "记录", "笔记", "作者", "he wrote", "she wrote", "user", "note")


def extract_single_json_object(text: str) -> Dict[str, Any]:
    content = str(text or "").strip()
    if not content:
        raise InvestmentJournalSchemaError("empty_response")
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        raise InvestmentJournalSchemaError("missing_json_object")
    try:
        payload = json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise InvestmentJournalSchemaError(f"invalid_json:{exc}") from exc
    if not isinstance(payload, dict):
        raise InvestmentJournalSchemaError("json_root_must_be_object")
    return payload


def parse_structured_journal_output(text: str) -> StructuredInvestmentJournalOutput:
    payload = extract_single_json_object(text)
    try:
        return StructuredInvestmentJournalOutput.model_validate(payload)
    except ValidationError as exc:
        raise InvestmentJournalSchemaError(str(exc)) from exc


def validate_structured_journal_output(
    output: StructuredInvestmentJournalOutput,
    *,
    context: JournalStructuringContext,
) -> None:
    del context
    text_fields: List[str] = [
        output.summary,
        output.investment_thesis or "",
        *output.reasons,
        *output.risks,
        *output.assumptions,
        *output.invalidation_conditions,
        *output.emotions,
        *output.cognitive_bias,
        *output.follow_up_items,
        *output.tags,
    ]
    for value in text_fields:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        for pattern in _ADVICE_PATTERNS:
            if pattern.search(normalized) and not any(marker in normalized.lower() for marker in _ATTRIBUTION_MARKERS):
                raise InvestmentJournalSafetyError("structured_output_contains_investment_advice")

