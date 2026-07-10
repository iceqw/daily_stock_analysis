# -*- coding: utf-8 -*-
"""Build low-sensitivity AI opinion generation context from DSA assets."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from src.storage import AnalysisHistory, DatabaseManager, DecisionSignalRecord, NewsIntel
from src.utils.data_processing import parse_json_field


class AnalysisOpinionSupportingSource(BaseModel):
    ref: str
    source_type: str
    label: str


class AnalysisOpinionSourceTrace(BaseModel):
    analysis_history_fields: List[str] = Field(default_factory=list)
    decision_signal_fields: List[str] = Field(default_factory=list)
    news_items_total: int = 0
    news_items_used: int = 0
    truncated_sections: List[str] = Field(default_factory=list)


class AnalysisOpinionContext(BaseModel):
    context_version: str = "analysis-opinion-context-v1"
    analysis_history_id: int
    query_id: Optional[str] = None
    stock_code: str
    stock_name: Optional[str] = None
    market: Optional[str] = None
    report_type: Optional[str] = None
    created_at: Optional[str] = None
    analysis_summary: Optional[str] = None
    key_points: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    watch_conditions: List[str] = Field(default_factory=list)
    catalysts: List[str] = Field(default_factory=list)
    internal_signal_evidence: List[str] = Field(default_factory=list)
    news_evidence: List[Dict[str, Optional[str]]] = Field(default_factory=list)
    supporting_sources: List[AnalysisOpinionSupportingSource] = Field(default_factory=list)
    source_trace: AnalysisOpinionSourceTrace = Field(default_factory=AnalysisOpinionSourceTrace)
    token_budget_target: int = 4500
    truncated: bool = False


class AnalysisOpinionContextBuilder:
    """Build a prompt-safe context for AI opinion generation."""

    MAX_KEY_POINTS = 5
    MAX_RISKS = 5
    MAX_WATCH_ITEMS = 5
    MAX_CATALYSTS = 4
    MAX_SIGNAL_EVIDENCE = 4
    MAX_NEWS_ITEMS = 6
    MAX_TEXT_LENGTH = 320
    _PROHIBITED_SIGNAL_TERMS = (
        "buy",
        "sell",
        "add position",
        "reduce position",
        "target price",
        "stop loss",
        "买入",
        "卖出",
        "加仓",
        "减仓",
        "目标价",
        "止损",
    )

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def build(self, analysis_history_id: int) -> AnalysisOpinionContext:
        record = self.db.get_analysis_history_by_id(int(analysis_history_id))
        if record is None:
            raise ValueError(f"Analysis history not found: {analysis_history_id}")
        raw_result = parse_json_field(getattr(record, "raw_result", None))
        signal = self._load_latest_internal_signal(record.id)
        news_items, total_news_items = self._load_news_items(record.query_id)

        key_points, key_points_truncated = self._extract_string_list(raw_result, ("key_points",))
        risks, risks_truncated = self._extract_string_list(
            raw_result,
            ("risk_summary", "risk_warning", "risks", "risk"),
        )
        watch_conditions, watch_truncated = self._extract_string_list_from_signal(
            signal,
            ("watch_conditions",),
        )
        catalysts, catalysts_truncated = self._extract_string_list_from_signal(
            signal,
            ("catalyst_summary",),
        )
        signal_evidence = self._extract_signal_evidence(signal)
        if not any(
            (
                self._trim_text(record.analysis_summary),
                key_points,
                risks,
                watch_conditions,
                catalysts,
                signal_evidence,
                news_items,
            )
        ):
            raise ValueError("analysis_history has no valid opinion context")

        analysis_history_fields: List[str] = []
        decision_signal_fields: List[str] = []
        truncated_sections: List[str] = []
        if record.analysis_summary:
            analysis_history_fields.append("analysis_summary")
        if key_points:
            analysis_history_fields.append("raw_result.key_points")
        if risks:
            analysis_history_fields.append("raw_result.risk_summary")
        if watch_conditions:
            decision_signal_fields.append("watch_conditions")
        if catalysts:
            decision_signal_fields.append("catalyst_summary")
        if signal_evidence:
            decision_signal_fields.append("evidence_json")
        if key_points_truncated:
            truncated_sections.append("key_points")
        if risks_truncated:
            truncated_sections.append("risks")
        if watch_truncated:
            truncated_sections.append("watch_conditions")
        if catalysts_truncated:
            truncated_sections.append("catalysts")
        if total_news_items > len(news_items):
            truncated_sections.append("news_evidence")

        supporting_sources: List[AnalysisOpinionSupportingSource] = []
        if record.analysis_summary:
            supporting_sources.append(
                AnalysisOpinionSupportingSource(
                    ref="analysis_summary",
                    source_type="analysis_history",
                    label="Analysis summary",
                )
            )
        for idx, _item in enumerate(key_points):
            supporting_sources.append(
                AnalysisOpinionSupportingSource(
                    ref=f"key_point:{idx}",
                    source_type="analysis_history",
                    label=f"Key point {idx + 1}",
                )
            )
        for idx, _item in enumerate(risks):
            supporting_sources.append(
                AnalysisOpinionSupportingSource(
                    ref=f"risk:{idx}",
                    source_type="analysis_history",
                    label=f"Risk {idx + 1}",
                )
            )
        for idx, _item in enumerate(watch_conditions):
            supporting_sources.append(
                AnalysisOpinionSupportingSource(
                    ref=f"watch_condition:{idx}",
                    source_type="internal_signal",
                    label=f"Internal watch condition {idx + 1}",
                )
            )
        for idx, _item in enumerate(catalysts):
            supporting_sources.append(
                AnalysisOpinionSupportingSource(
                    ref=f"catalyst:{idx}",
                    source_type="internal_signal",
                    label=f"Internal catalyst {idx + 1}",
                )
            )
        for idx, _item in enumerate(signal_evidence):
            supporting_sources.append(
                AnalysisOpinionSupportingSource(
                    ref=f"internal_evidence:{idx}",
                    source_type="internal_signal",
                    label=f"Internal evidence {idx + 1}",
                )
            )
        for idx, item in enumerate(news_items):
            supporting_sources.append(
                AnalysisOpinionSupportingSource(
                    ref=f"news:{idx}",
                    source_type="news_intel",
                    label=item.get("title") or f"News {idx + 1}",
                )
            )

        return AnalysisOpinionContext(
            analysis_history_id=int(record.id),
            query_id=record.query_id,
            stock_code=str(record.code or "").strip(),
            stock_name=record.name,
            market=self._infer_market(record.code),
            report_type=record.report_type,
            created_at=record.created_at.isoformat() if record.created_at else None,
            analysis_summary=self._trim_text(record.analysis_summary),
            key_points=key_points,
            risks=risks,
            watch_conditions=watch_conditions,
            catalysts=catalysts,
            internal_signal_evidence=signal_evidence,
            news_evidence=news_items,
            supporting_sources=supporting_sources,
            source_trace=AnalysisOpinionSourceTrace(
                analysis_history_fields=analysis_history_fields,
                decision_signal_fields=decision_signal_fields,
                news_items_total=total_news_items,
                news_items_used=len(news_items),
                truncated_sections=truncated_sections,
            ),
            truncated=bool(
                key_points_truncated
                or risks_truncated
                or watch_truncated
                or catalysts_truncated
                or total_news_items > len(news_items)
            ),
        )

    def _load_latest_internal_signal(self, analysis_history_id: int) -> Optional[DecisionSignalRecord]:
        with self.db.get_session() as session:
            return session.execute(
                select(DecisionSignalRecord)
                .where(
                    DecisionSignalRecord.source_type == "analysis",
                    DecisionSignalRecord.source_report_id == int(analysis_history_id),
                )
                .order_by(desc(DecisionSignalRecord.created_at), desc(DecisionSignalRecord.id))
                .limit(1)
            ).scalar_one_or_none()

    def _load_news_items(self, query_id: Optional[str]) -> tuple[List[Dict[str, Optional[str]]], int]:
        if not query_id:
            return [], 0
        rows = self.db.get_news_intel_by_query_id(query_id=query_id, limit=self.MAX_NEWS_ITEMS + 1)
        items: List[Dict[str, Optional[str]]] = []
        for row in rows[: self.MAX_NEWS_ITEMS]:
            items.append(
                {
                    "title": self._trim_text(row.title),
                    "summary": self._trim_text(row.snippet),
                    "source": self._trim_text(row.source),
                    "published_at": row.published_date.isoformat() if row.published_date else None,
                }
            )
        return items, len(rows)

    def _extract_signal_evidence(self, signal: Optional[DecisionSignalRecord]) -> List[str]:
        if signal is None:
            return []
        items: List[str] = []
        parsed = parse_json_field(signal.evidence_json)
        if isinstance(parsed, list):
            for entry in parsed:
                text = self._trim_text(entry)
                if text and text not in items and not self._contains_prohibited_signal_term(text):
                    items.append(text)
        return items[: self.MAX_SIGNAL_EVIDENCE]

    def _extract_string_list_from_signal(
        self,
        signal: Optional[DecisionSignalRecord],
        field_names: tuple[str, ...],
    ) -> tuple[List[str], bool]:
        if signal is None:
            return [], False
        values: List[str] = []
        for field_name in field_names:
            raw = getattr(signal, field_name, None)
            values.extend(self._normalize_list_candidate(raw))
        limit = self.MAX_WATCH_ITEMS if field_names == ("watch_conditions",) else self.MAX_CATALYSTS
        filtered = [value for value in values if not self._contains_prohibited_signal_term(value)]
        return filtered[:limit], len(filtered) > limit

    def _extract_string_list(self, raw_result: Any, field_names: tuple[str, ...]) -> tuple[List[str], bool]:
        payload = raw_result if isinstance(raw_result, dict) else {}
        values: List[str] = []
        for field_name in field_names:
            candidate = payload.get(field_name)
            values.extend(self._normalize_list_candidate(candidate))
            for container_key in ("dashboard", "summary"):
                container = payload.get(container_key)
                if isinstance(container, dict):
                    values.extend(self._normalize_list_candidate(container.get(field_name)))
        if field_names == ("key_points",):
            return values[: self.MAX_KEY_POINTS], len(values) > self.MAX_KEY_POINTS
        return values[: self.MAX_RISKS], len(values) > self.MAX_RISKS

    def _normalize_list_candidate(self, value: Any) -> List[str]:
        items: List[str] = []
        if isinstance(value, str):
            normalized = self._trim_text(value)
            if normalized:
                items.append(normalized)
        elif isinstance(value, list):
            for entry in value:
                normalized = self._trim_text(entry)
                if normalized and normalized not in items:
                    items.append(normalized)
        elif isinstance(value, dict):
            for entry in value.values():
                normalized = self._trim_text(entry)
                if normalized and normalized not in items:
                    items.append(normalized)
        return items

    @classmethod
    def _trim_text(cls, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if len(text) <= cls.MAX_TEXT_LENGTH:
            return text
        return f"{text[: cls.MAX_TEXT_LENGTH - 3]}..."

    @staticmethod
    def _infer_market(code: Any) -> Optional[str]:
        normalized = str(code or "").strip().upper()
        if not normalized:
            return None
        if normalized.startswith("HK"):
            return "hk"
        if normalized.isalpha():
            return "us"
        return "cn"

    @classmethod
    def _contains_prohibited_signal_term(cls, value: str) -> bool:
        lowered = str(value or "").strip().lower()
        return any(term in lowered for term in cls._PROHIBITED_SIGNAL_TERMS)
