# -*- coding: utf-8 -*-
"""Schema parsing and safety validation for AI opinion outputs."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from src.services.ai_opinion_context_builder import AnalysisOpinionContext


class AIOpinionSchemaError(ValueError):
    """Raised when model output is not valid structured JSON."""


class AIOpinionSafetyError(ValueError):
    """Raised when parsed output violates AI investment safety rules."""


class AIOpinionConfidence(BaseModel):
    level: Literal["low", "medium", "medium_high"]
    rationale: str = Field(..., min_length=1, max_length=400)


class AIOpinionEvidenceItem(BaseModel):
    statement: str = Field(..., min_length=1, max_length=400)
    source_type: Literal["analysis_history", "internal_signal", "news_intel", "derived_summary"]
    source_ref: Optional[str] = Field(default=None, max_length=64)


class AIOpinionStructuredOutput(BaseModel):
    schema_version: Literal["ai-opinion-output-v1"]
    summary: str = Field(..., min_length=1, max_length=800)
    key_findings: List[str] = Field(default_factory=list, max_length=8)
    supporting_evidence: List[AIOpinionEvidenceItem] = Field(default_factory=list, max_length=12)
    risks: List[str] = Field(default_factory=list, max_length=8)
    uncertainties: List[str] = Field(default_factory=list, max_length=8)
    limitations: List[str] = Field(default_factory=list, max_length=8)
    things_to_watch: List[str] = Field(default_factory=list, max_length=8)
    investment_discipline_notes: List[str] = Field(default_factory=list, max_length=8)
    confidence: AIOpinionConfidence
    disclaimer: str = Field(..., min_length=1, max_length=800)


_BANNED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"建议\s*(立即)?\s*(买入|卖出|加仓|减仓)",
        r"\b(recommend|buy|sell)\b",
        r"\b(add(\s+to)?\s+position|reduce\s+position)\b",
        r"\b(target price|stop loss|take profit)\b",
        r"目标价",
        r"止损",
        r"止盈",
        r"必涨",
        r"必跌",
        r"稳赚",
        r"确定收益",
        r"guaranteed return",
    )
]


def extract_single_json_object(text: str) -> Dict[str, Any]:
    content = str(text or "").strip()
    if not content:
        raise AIOpinionSchemaError("empty_response")
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        raise AIOpinionSchemaError("missing_json_object")
    try:
        payload = json.loads(content[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIOpinionSchemaError(f"invalid_json:{exc}") from exc
    if not isinstance(payload, dict):
        raise AIOpinionSchemaError("json_root_must_be_object")
    return payload


def parse_ai_opinion_output(text: str) -> AIOpinionStructuredOutput:
    payload = extract_single_json_object(text)
    try:
        return AIOpinionStructuredOutput.model_validate(payload)
    except ValidationError as exc:
        raise AIOpinionSchemaError(str(exc)) from exc


def validate_ai_opinion_output(
    output: AIOpinionStructuredOutput,
    *,
    context: AnalysisOpinionContext,
) -> None:
    allowed_ref_map = {item.ref: item.source_type for item in context.supporting_sources}
    text_fields: List[str] = [
        output.summary,
        output.disclaimer,
        output.confidence.rationale,
        *output.key_findings,
        *output.risks,
        *output.uncertainties,
        *output.limitations,
        *output.things_to_watch,
        *output.investment_discipline_notes,
        *(item.statement for item in output.supporting_evidence),
    ]
    for value in text_fields:
        for pattern in _BANNED_PATTERNS:
            if pattern.search(value or ""):
                raise AIOpinionSafetyError("opinion_contains_prohibited_investment_advice")
    for item in output.supporting_evidence:
        if item.source_type != "derived_summary" and not item.source_ref:
            raise AIOpinionSafetyError("missing_source_ref_for_evidence")
        if item.source_ref and item.source_ref not in allowed_ref_map:
            raise AIOpinionSafetyError(f"unsupported_source_ref:{item.source_ref}")
        if item.source_ref and item.source_type != allowed_ref_map[item.source_ref]:
            raise AIOpinionSafetyError(f"source_type_mismatch:{item.source_ref}")


def render_ai_opinion_content(output: AIOpinionStructuredOutput) -> str:
    sections: List[str] = [f"## Summary\n{output.summary}"]
    if output.key_findings:
        sections.append("## Key Findings\n" + "\n".join(f"- {item}" for item in output.key_findings))
    if output.supporting_evidence:
        evidence_lines = []
        for item in output.supporting_evidence:
            suffix = f" ({item.source_type}: {item.source_ref})" if item.source_ref else f" ({item.source_type})"
            evidence_lines.append(f"- {item.statement}{suffix}")
        sections.append("## Supporting Evidence\n" + "\n".join(evidence_lines))
    for title, items in (
        ("Risks", output.risks),
        ("Uncertainties", output.uncertainties),
        ("Limitations", output.limitations),
        ("Things to Watch", output.things_to_watch),
        ("Investment Discipline Notes", output.investment_discipline_notes),
    ):
        if items:
            sections.append(f"## {title}\n" + "\n".join(f"- {item}" for item in items))
    sections.append(
        "## Confidence\n"
        f"- level: {output.confidence.level}\n"
        f"- rationale: {output.confidence.rationale}"
    )
    sections.append(f"## Disclaimer\n{output.disclaimer}")
    return "\n\n".join(sections).strip()
