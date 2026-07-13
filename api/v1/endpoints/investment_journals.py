# -*- coding: utf-8 -*-
"""Investment journal API endpoints."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query, status

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.investment_journals import (
    AnalysisJournalSyncResponse,
    InvestmentJournalEntryItem,
    InvestmentJournalListResponse,
    InvestmentJournalStructuringAccepted,
    ManualJournalEntryCreateRequest,
    ManualJournalEntryUpdateRequest,
)
from src.services.investment_journal_structuring_service import InvestmentJournalStructuringService
from src.services.investment_journal_service import (
    InvestmentJournalConflictError,
    InvestmentJournalNotFoundError,
    InvestmentJournalService,
    InvestmentJournalStructuringUnavailableError,
    InvestmentJournalUnsupportedHistoryError,
)
from src.services.task_queue import get_task_queue


logger = logging.getLogger(__name__)
router = APIRouter()


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": "validation_error", "message": str(exc)})


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": "not_found", "message": str(exc)})


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail={"error": "conflict", "message": str(exc)})


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"error": "context_unavailable", "message": str(exc)},
    )


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return HTTPException(status_code=500, detail={"error": "internal_error", "message": message})


def _submit_structuring_task(entry: dict, *, message: str) -> InvestmentJournalStructuringAccepted:
    entry_id = int(entry["id"])
    task_id = f"journal_structure_{entry_id}_{uuid.uuid4().hex}"
    task = get_task_queue().submit_background_task(
        lambda: InvestmentJournalStructuringService().structure(entry_id),
        stock_code=f"journal_{entry['stock_code']}_{entry_id}",
        stock_name=f"Journal {entry_id}",
        report_type="investment_journal_structuring",
        message=message,
        task_id=task_id,
        trace_id=task_id,
    )
    return InvestmentJournalStructuringAccepted(
        entry=InvestmentJournalEntryItem(**entry),
        task_id=task.task_id,
        trace_id=task.trace_id or task.task_id,
        task_status=task.status.value,
        message=task.message,
    )


@router.get(
    "",
    response_model=InvestmentJournalListResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="List investment journal timeline entries for a stock",
)
def list_investment_journal_entries(
    stock_code: str = Query(..., min_length=1),
    market: str = Query(..., min_length=2),
    entry_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=120),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
) -> InvestmentJournalListResponse:
    service = InvestmentJournalService()
    try:
        return InvestmentJournalListResponse(
            **service.list_entries(
                stock_code=stock_code,
                market=market,
                entry_type=entry_type,
                page=page,
                page_size=page_size,
                search=search,
                sort_by=sort_by,
                sort_order=sort_order,
            )
        )
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("List investment journal entries failed", exc)


@router.get(
    "/{entry_id}",
    response_model=InvestmentJournalEntryItem,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get one investment journal entry",
)
def get_investment_journal_entry(entry_id: int) -> InvestmentJournalEntryItem:
    service = InvestmentJournalService()
    try:
        return InvestmentJournalEntryItem(**service.get_entry(entry_id))
    except InvestmentJournalNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("Get investment journal entry failed", exc)


@router.post(
    "/manual",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InvestmentJournalStructuringAccepted,
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Create a manual investment note and accept AI structuring",
)
def create_manual_investment_journal_entry(
    request: ManualJournalEntryCreateRequest,
) -> InvestmentJournalStructuringAccepted:
    service = InvestmentJournalService()
    try:
        created = service.create_manual_entry(**request.model_dump())
        pending = service.create_pending_structuring(int(created["id"]))
        return _submit_structuring_task(
            pending,
            message="Investment journal structuring task accepted",
        )
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create manual investment journal entry failed", exc)


@router.patch(
    "/manual/{entry_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InvestmentJournalStructuringAccepted,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Update a manual investment note and accept AI structuring",
)
def update_manual_investment_journal_entry(
    entry_id: int,
    request: ManualJournalEntryUpdateRequest,
) -> InvestmentJournalStructuringAccepted:
    service = InvestmentJournalService()
    try:
        updated = service.update_manual_entry(entry_id, **request.model_dump(exclude_unset=True))
        pending = service.create_pending_structuring(int(updated["id"]))
        return _submit_structuring_task(
            pending,
            message="Investment journal restructuring task accepted",
        )
    except InvestmentJournalNotFoundError as exc:
        raise _not_found(exc)
    except InvestmentJournalConflictError as exc:
        raise _conflict(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Update manual investment journal entry failed", exc)


@router.post(
    "/sync-analysis/{analysis_history_id}",
    response_model=AnalysisJournalSyncResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Idempotently create an analysis journal entry from analysis_history",
)
def sync_analysis_investment_journal_entry(analysis_history_id: int) -> AnalysisJournalSyncResponse:
    service = InvestmentJournalService()
    try:
        return AnalysisJournalSyncResponse(**service.sync_analysis_entry(analysis_history_id))
    except InvestmentJournalUnsupportedHistoryError as exc:
        raise _bad_request(exc)
    except InvestmentJournalNotFoundError as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Sync analysis investment journal entry failed", exc)


@router.post(
    "/{entry_id}/structure",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InvestmentJournalStructuringAccepted,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Create a pending AI structuring task for one manual journal entry",
)
def structure_investment_journal_entry(entry_id: int) -> InvestmentJournalStructuringAccepted:
    service = InvestmentJournalService()
    try:
        entry = service.create_pending_structuring(entry_id)
        return _submit_structuring_task(entry, message="Investment journal structuring task accepted")
    except InvestmentJournalNotFoundError as exc:
        raise _not_found(exc)
    except InvestmentJournalConflictError as exc:
        raise _conflict(exc)
    except InvestmentJournalStructuringUnavailableError as exc:
        raise _unprocessable(exc)
    except Exception as exc:
        raise _internal_error("Create investment journal structuring task failed", exc)


@router.post(
    "/{entry_id}/retry-structure",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=InvestmentJournalStructuringAccepted,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Retry AI structuring for one manual journal entry",
)
def retry_structure_investment_journal_entry(entry_id: int) -> InvestmentJournalStructuringAccepted:
    service = InvestmentJournalService()
    try:
        entry = service.retry_structuring(entry_id)
        return _submit_structuring_task(entry, message="Investment journal structuring retry task accepted")
    except InvestmentJournalNotFoundError as exc:
        raise _not_found(exc)
    except InvestmentJournalConflictError as exc:
        raise _conflict(exc)
    except InvestmentJournalStructuringUnavailableError as exc:
        raise _unprocessable(exc)
    except Exception as exc:
        raise _internal_error("Retry investment journal structuring task failed", exc)
