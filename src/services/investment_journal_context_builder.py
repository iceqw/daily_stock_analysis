# -*- coding: utf-8 -*-
"""Build prompt-safe context for structuring manual investment journal notes."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.storage import DatabaseManager, InvestmentJournalEntry


class JournalStructuringSourceTrace(BaseModel):
    fields_used: List[str] = Field(default_factory=list)


class JournalStructuringContext(BaseModel):
    context_version: str = "investment-journal-structuring-context-v1"
    journal_entry_id: int
    stock_code: str
    market: str
    entry_type: str
    created_at: Optional[str] = None
    content_language: str
    raw_content: str
    source_trace: JournalStructuringSourceTrace = Field(default_factory=JournalStructuringSourceTrace)


class InvestmentJournalContextBuilder:
    """Build a minimal context from one manual journal entry only."""

    MAX_RAW_CONTENT_LENGTH = 12000
    _CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
    _KOREAN_PATTERN = re.compile(r"[\uac00-\ud7af]")
    _JAPANESE_PATTERN = re.compile(r"[\u3040-\u30ff]")

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager.get_instance()

    def build(self, entry_id: int) -> JournalStructuringContext:
        with self.db.get_session() as session:
            row = session.get(InvestmentJournalEntry, int(entry_id))
            if row is None:
                raise ValueError(f"Investment journal entry not found: {entry_id}")
            return self.build_from_entry(row)

    def build_from_entry(self, row: InvestmentJournalEntry) -> JournalStructuringContext:
        if row.entry_type != "manual":
            raise ValueError("only manual journal entries support AI structuring")
        raw_content = str(row.raw_content or "").strip()
        if not raw_content:
            raise ValueError("investment journal entry has no raw_content to structure")
        trimmed_content = self._trim_text(raw_content)
        return JournalStructuringContext(
            journal_entry_id=int(row.id),
            stock_code=str(row.stock_code or "").strip(),
            market=str(row.market or "").strip().lower(),
            entry_type=str(row.entry_type or "").strip().lower(),
            created_at=row.created_at.isoformat() if row.created_at else None,
            content_language=self._infer_language(trimmed_content),
            raw_content=trimmed_content,
            source_trace=JournalStructuringSourceTrace(
                fields_used=["stock_code", "market", "created_at", "raw_content"]
            ),
        )

    @classmethod
    def _trim_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if len(text) <= cls.MAX_RAW_CONTENT_LENGTH:
            return text
        return text[: cls.MAX_RAW_CONTENT_LENGTH - 3].rstrip() + "..."

    @classmethod
    def _infer_language(cls, text: str) -> str:
        if cls._JAPANESE_PATTERN.search(text):
            return "ja"
        if cls._KOREAN_PATTERN.search(text):
            return "ko"
        if cls._CJK_PATTERN.search(text):
            return "zh"
        return "en"
