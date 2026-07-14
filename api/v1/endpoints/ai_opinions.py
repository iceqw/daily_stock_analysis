# -*- coding: utf-8 -*-
"""AI opinion API endpoints."""

from __future__ import annotations

import logging
import uuid

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from api.v1.schemas.ai_opinions import (
    AIOpinionFeedbackRequest,
    AIOpinionGenerateAccepted,
    AIOpinionItem,
    AIOpinionListResponse,
)
from api.v1.schemas.common import ErrorResponse
from src.services.ai_opinion_generation_service import AIOpinionGenerationService
from src.services.ai_opinion_service import (
    AIOpinionConflictError,
    AIOpinionContextUnavailableError,
    AIOpinionNotFoundError,
    AIOpinionService,
    AIOpinionSourceUnavailableError,
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


@router.get(
    "",
    response_model=AIOpinionListResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="List AI opinions by analysis history or stock",
)
def list_ai_opinions(
    analysis_history_id: Optional[int] = Query(None, gt=0),
    stock_code: Optional[str] = Query(None, min_length=1),
    market: Optional[str] = Query(None, min_length=1),
    current_only: bool = Query(False),
    page: int = Query(1, gt=0),
    page_size: int = Query(20, gt=0, le=100),
    search: Optional[str] = Query(None, max_length=120),
    generation_status: Optional[str] = Query(None),
    source_status: Optional[str] = Query(None),
    feedback_value: Optional[str] = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
) -> AIOpinionListResponse:
    service = AIOpinionService()
    try:
        if analysis_history_id is None and not stock_code:
            raise ValueError("analysis_history_id or stock_code is required")
        if analysis_history_id is not None and stock_code:
            raise ValueError("analysis_history_id and stock_code cannot be used together")
        if stock_code:
            # market is accepted for frontend route symmetry; AI opinions are
            # still linked through analysis_history, whose persisted key is code.
            _ = market
            return AIOpinionListResponse(
                **service.list_opinions_by_stock(
                    stock_code=stock_code,
                    current_only=current_only,
                    page=page,
                    page_size=page_size,
                    search=search,
                    generation_status=generation_status,
                    source_status=source_status,
                    feedback_value=feedback_value,
                    sort_by=sort_by,
                    sort_order=sort_order,
                )
            )
        return AIOpinionListResponse(
            **service.list_opinions(
                analysis_history_id=analysis_history_id,
                current_only=current_only,
                page=page,
                page_size=page_size,
            )
        )
    except AIOpinionNotFoundError as exc:
        raise _not_found(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("List AI opinions failed", exc)


@router.get(
    "/{opinion_id}",
    response_model=AIOpinionItem,
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get one AI opinion",
)
def get_ai_opinion(opinion_id: int) -> AIOpinionItem:
    service = AIOpinionService()
    try:
        return AIOpinionItem(**service.get_opinion(opinion_id))
    except AIOpinionNotFoundError as exc:
        raise _not_found(exc)
    except Exception as exc:
        raise _internal_error("Get AI opinion failed", exc)


@router.put(
    "/{opinion_id}/feedback",
    response_model=AIOpinionItem,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Store user feedback for one AI opinion",
)
def update_ai_opinion_feedback(
    opinion_id: int,
    request: AIOpinionFeedbackRequest,
) -> AIOpinionItem:
    service = AIOpinionService()
    try:
        return AIOpinionItem(**service.update_feedback(opinion_id, **request.model_dump()))
    except AIOpinionNotFoundError as exc:
        raise _not_found(exc)
    except AIOpinionConflictError as exc:
        raise _conflict(exc)
    except AIOpinionSourceUnavailableError as exc:
        raise _conflict(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Update AI opinion feedback failed", exc)


@router.post(
    "/generate/{analysis_history_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AIOpinionGenerateAccepted,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Create a pending AI opinion generation task",
)
def generate_ai_opinion(analysis_history_id: int) -> AIOpinionGenerateAccepted:
    service = AIOpinionService()
    try:
        created = service.create_pending_generation(analysis_history_id=analysis_history_id)
        opinion_id = int(created["id"])
        task_id = f"ai_opinion_generate_{opinion_id}_{uuid.uuid4().hex}"
        task = get_task_queue().submit_background_task(
            lambda: AIOpinionGenerationService().generate(opinion_id),
            stock_code=f"ai_opinion_{created['analysis_history_id'] or opinion_id}",
            stock_name=f"AI Opinion {opinion_id}",
            report_type="ai_opinion_generation",
            message="AI Opinion generation task accepted",
            task_id=task_id,
            trace_id=task_id,
        )
        return AIOpinionGenerateAccepted(
            opinion=AIOpinionItem(**created),
            task_id=task.task_id,
            trace_id=task.trace_id or task.task_id,
            task_status=task.status.value,
            message=task.message,
        )
    except AIOpinionNotFoundError as exc:
        raise _not_found(exc)
    except AIOpinionConflictError as exc:
        raise _conflict(exc)
    except AIOpinionContextUnavailableError as exc:
        raise _unprocessable(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create AI opinion generation task failed", exc)


@router.post(
    "/{opinion_id}/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AIOpinionGenerateAccepted,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
    summary="Create a new AI opinion regeneration task",
)
def regenerate_ai_opinion(opinion_id: int) -> AIOpinionGenerateAccepted:
    service = AIOpinionService()
    try:
        created = service.regenerate_opinion(opinion_id)
        new_opinion_id = int(created["id"])
        task_id = f"ai_opinion_generate_{new_opinion_id}_{uuid.uuid4().hex}"
        task = get_task_queue().submit_background_task(
            lambda: AIOpinionGenerationService().generate(new_opinion_id),
            stock_code=f"ai_opinion_{created['analysis_history_id'] or new_opinion_id}",
            stock_name=f"AI Opinion {new_opinion_id}",
            report_type="ai_opinion_generation",
            message="AI Opinion regeneration task accepted",
            task_id=task_id,
            trace_id=task_id,
        )
        return AIOpinionGenerateAccepted(
            opinion=AIOpinionItem(**created),
            task_id=task.task_id,
            trace_id=task.trace_id or task.task_id,
            task_status=task.status.value,
            message=task.message,
        )
    except AIOpinionNotFoundError as exc:
        raise _not_found(exc)
    except (AIOpinionConflictError, AIOpinionSourceUnavailableError) as exc:
        raise _conflict(exc)
    except AIOpinionContextUnavailableError as exc:
        raise _unprocessable(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create AI opinion regeneration task failed", exc)


@router.post(
    "/{opinion_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AIOpinionGenerateAccepted,
    summary="Retry one failed AI opinion using its frozen snapshot",
)
def retry_ai_opinion(opinion_id: int) -> AIOpinionGenerateAccepted:
    service = AIOpinionService()
    try:
        created = service.retry_opinion(opinion_id)
        new_id = int(created["id"])
        task_id = f"ai_opinion_retry_{new_id}_{uuid.uuid4().hex}"
        task = get_task_queue().submit_background_task(
            lambda: AIOpinionGenerationService().generate(new_id),
            stock_code=f"ai_opinion_{created['analysis_history_id'] or new_id}",
            stock_name=f"AI Opinion {new_id}", report_type="ai_opinion_generation",
            message="AI Opinion retry task accepted", task_id=task_id, trace_id=task_id,
        )
        return AIOpinionGenerateAccepted(
            opinion=AIOpinionItem(**created), task_id=task.task_id,
            trace_id=task.trace_id or task.task_id, task_status=task.status.value,
            message=task.message,
        )
    except AIOpinionNotFoundError as exc:
        raise _not_found(exc)
    except AIOpinionConflictError as exc:
        raise _conflict(exc)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception as exc:
        raise _internal_error("Create AI opinion retry task failed", exc)
