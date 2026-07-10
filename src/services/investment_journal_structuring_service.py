# -*- coding: utf-8 -*-
"""Execute AI structuring for one manual investment journal entry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.analyzer import GeminiAnalyzer
from src.config import get_config
from src.repositories.investment_journal_repo import (
    InvestmentJournalMutationConflictError,
    InvestmentJournalRepository,
    InvestmentJournalStateTransitionError,
)
from src.services.ai_opinion_prompt_loader import load_prompt
from src.services.investment_journal_context_builder import InvestmentJournalContextBuilder
from src.services.investment_journal_service import (
    InvestmentJournalNotFoundError,
    InvestmentJournalService,
)
from src.services.investment_journal_validator import (
    InvestmentJournalSafetyError,
    InvestmentJournalSchemaError,
    parse_structured_journal_output,
    validate_structured_journal_output,
)
from src.storage import DatabaseManager


class InvestmentJournalStructuringService:
    """Run one structuring attempt against the shared GenerationBackend."""

    PROMPT_NAME = "journal"
    PROMPT_VERSION = "v1"
    STRUCTURED_VERSION = "investment-journal-structured-v1"

    def __init__(
        self,
        *,
        db_manager: Optional[DatabaseManager] = None,
        repo: Optional[InvestmentJournalRepository] = None,
        journal_service: Optional[InvestmentJournalService] = None,
        analyzer: Optional[GeminiAnalyzer] = None,
        context_builder: Optional[InvestmentJournalContextBuilder] = None,
    ) -> None:
        self.db = db_manager or DatabaseManager.get_instance()
        self.repo = repo or InvestmentJournalRepository(self.db)
        self.journal_service = journal_service or InvestmentJournalService(repo=self.repo, db_manager=self.db)
        self.analyzer = analyzer or GeminiAnalyzer(config=get_config())
        self.context_builder = context_builder or InvestmentJournalContextBuilder(self.db)

    def structure(self, entry_id: int) -> Dict[str, Any]:
        row = self.repo.get(int(entry_id))
        if row is None:
            raise InvestmentJournalNotFoundError(f"Investment journal entry not found: {entry_id}")
        if row.entry_type != "manual":
            raise InvestmentJournalMutationConflictError("only manual journal entries can be structured")

        self.repo.mark_processing(int(entry_id))
        try:
            context = self.context_builder.build(int(entry_id))
            prompts = load_prompt(self.PROMPT_NAME, self.PROMPT_VERSION)
            context_json = json.dumps(context.model_dump(mode="json"), ensure_ascii=False, indent=2)
            user_prompt = prompts["user"].replace("{{CONTEXT_JSON}}", context_json)
            generation_config = {
                "temperature": 0.1,
                "max_output_tokens": 1800,
            }
            result = self.analyzer._get_generation_backend().generate(
                user_prompt,
                generation_config,
                system_prompt=prompts["system"],
                response_validator=lambda text: parse_structured_journal_output(text),
                audit_context={
                    "feature": "investment_journal_structuring",
                    "journal_entry_id": int(entry_id),
                    "stock_code": context.stock_code,
                },
            )
            parsed = parse_structured_journal_output(result.text)
            validate_structured_journal_output(parsed, context=context)
            completed = self.repo.mark_completed(
                int(entry_id),
                structured_output_json=json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False),
                model=result.model,
                provider=result.provider,
                temperature=float(generation_config["temperature"]),
                prompt_version=f"{self.PROMPT_NAME}-{self.PROMPT_VERSION}",
                structured_version=self.STRUCTURED_VERSION,
                structured_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            if completed is None:
                raise RuntimeError("investment_journal_completion_persist_failed")
            return self.journal_service.get_entry(completed.id)
        except (InvestmentJournalStateTransitionError, InvestmentJournalMutationConflictError):
            raise
        except (InvestmentJournalSafetyError, InvestmentJournalSchemaError) as exc:
            self.repo.mark_failed(int(entry_id), error_message=str(exc))
            raise
        except Exception as exc:
            self.repo.mark_failed(int(entry_id), error_message=str(exc)[:500])
            raise
