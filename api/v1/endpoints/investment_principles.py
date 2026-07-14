# -*- coding: utf-8 -*-
"""Investment principle API endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.investment_principles import (
    InvestmentPrincipleCreateRequest,
    InvestmentPrincipleDetailResponse,
    InvestmentPrincipleListItemResponse,
    InvestmentPrincipleListResponse,
    InvestmentPrincipleResponse,
    InvestmentPrincipleSourceCreate,
    InvestmentPrincipleSourceResponse,
    InvestmentPrincipleStatusActionRequest,
    InvestmentPrincipleUpdateRequest,
    InvestmentPrincipleVersionListResponse,
    InvestmentPrincipleVersionResponse,
)
from src.services.investment_principle_service import (
    InvestmentPrincipleConflictError,
    InvestmentPrincipleDataIntegrityError,
    InvestmentPrincipleNotFoundError,
    InvestmentPrincipleService,
    InvestmentPrincipleValidationError,
)


logger = logging.getLogger(__name__)
router = APIRouter()


def _error(status_code: int, error: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"error": error, "message": message})


def _bad_request(exc: Exception) -> HTTPException:
    return _error(400, "validation_error", str(exc))


def _not_found(exc: Exception) -> HTTPException:
    return _error(404, "not_found", str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return _error(409, "conflict", str(exc))


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.error("%s: %s", message, exc, exc_info=True)
    return _error(500, "data_integrity_error", message)


def _source_payload(source: InvestmentPrincipleSourceCreate) -> Dict[str, Any]:
    return source.model_dump()


def _to_source_response(source: Any) -> InvestmentPrincipleSourceResponse:
    return InvestmentPrincipleSourceResponse(
        id=int(source.id),
        principle_version_id=int(source.principle_version_id),
        source_type=source.source_type,
        source_id=None if source.source_id is None else int(source.source_id),
        source_excerpt=source.source_excerpt,
        source_status=source.source_status,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _to_version_response(version: Any, *, sources: Optional[list[Any]] = None) -> InvestmentPrincipleVersionResponse:
    return InvestmentPrincipleVersionResponse(
        id=int(version.id),
        principle_id=int(version.principle_id),
        version=int(version.version),
        title=version.title,
        statement=version.statement,
        rationale=version.rationale,
        category=version.category,
        severity=version.severity,
        scope_type=version.scope_type,
        scope_market=version.scope_market,
        scope_stock_code=version.scope_stock_code,
        change_note=version.change_note,
        created_at=version.created_at,
        source_count=0 if sources is None else len(sources),
        sources=None if sources is None else [_to_source_response(row) for row in sources],
    )


def _to_principle_response(principle: Any) -> InvestmentPrincipleResponse:
    return InvestmentPrincipleResponse(
        id=int(principle.id),
        status=principle.status,
        current_version=int(principle.current_version),
        created_at=principle.created_at,
        updated_at=principle.updated_at,
        status_changed_at=principle.status_changed_at,
        activated_at=principle.activated_at,
        archived_at=principle.archived_at,
        rejected_at=principle.rejected_at,
    )


def _to_detail_response(detail: Any, service: InvestmentPrincipleService) -> InvestmentPrincipleDetailResponse:
    return InvestmentPrincipleDetailResponse(
        principle=_to_principle_response(detail.principle),
        current_version=_to_version_response(detail.version, sources=detail.sources),
        sources=[_to_source_response(row) for row in detail.sources],
    )


def _to_list_response(result: Any, service: InvestmentPrincipleService) -> InvestmentPrincipleListResponse:
    items = []
    for item in result.items:
        sources = service.list_version_sources(item.version.id)
        items.append(
            InvestmentPrincipleListItemResponse(
                principle=_to_principle_response(item.principle),
                current_version=_to_version_response(item.version),
                source_count=len(sources),
            )
        )
    return InvestmentPrincipleListResponse(
        items=items,
        total=int(result.total),
        page=int(result.page),
        page_size=int(result.page_size),
    )


def _service(request: Request) -> InvestmentPrincipleService:
    return InvestmentPrincipleService(db_manager=getattr(request.app.state, "database_manager", None))


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=InvestmentPrincipleDetailResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def create_investment_principle(request: InvestmentPrincipleCreateRequest, service: InvestmentPrincipleService = Depends(_service)):
    try:
        detail = service.create_principle(
            **request.model_dump(exclude={"sources"}),
            sources=[_source_payload(source) for source in request.sources],
        )
        return _to_detail_response(detail, service)
    except InvestmentPrincipleNotFoundError as exc:
        raise _not_found(exc)
    except InvestmentPrincipleConflictError as exc:
        raise _conflict(exc)
    except InvestmentPrincipleValidationError as exc:
        raise _bad_request(exc)
    except InvestmentPrincipleDataIntegrityError as exc:
        raise _internal_error("Create investment principle failed", exc)
    except Exception as exc:
        raise _internal_error("Create investment principle failed", exc)


@router.get("", response_model=InvestmentPrincipleListResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def list_investment_principles(
    status: Optional[str] = Query(None), category: Optional[str] = Query(None), severity: Optional[str] = Query(None),
    scope_type: Optional[str] = Query(None), market: Optional[str] = Query(None), stock_code: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None), page: int = Query(1), page_size: int = Query(20),
    sort_by: str = Query("updated_at"), sort_order: str = Query("desc"),
    service: InvestmentPrincipleService = Depends(_service),
):
    try:
        return _to_list_response(service.list_principles(
            status=status, category=category, severity=severity, scope_type=scope_type,
            market=market, stock_code=stock_code, keyword=keyword, page=page, page_size=page_size,
            sort_by=sort_by, sort_order=sort_order,
        ), service)
    except InvestmentPrincipleValidationError as exc:
        raise _bad_request(exc)
    except InvestmentPrincipleDataIntegrityError as exc:
        raise _internal_error("List investment principles failed", exc)
    except Exception as exc:
        raise _internal_error("List investment principles failed", exc)


@router.get("/{principle_id}", response_model=InvestmentPrincipleDetailResponse, responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def get_investment_principle(principle_id: int, service: InvestmentPrincipleService = Depends(_service)):
    try:
        return _to_detail_response(service.get_principle(principle_id), service)
    except InvestmentPrincipleNotFoundError as exc:
        raise _not_found(exc)
    except InvestmentPrincipleDataIntegrityError as exc:
        raise _internal_error("Get investment principle failed", exc)
    except Exception as exc:
        raise _internal_error("Get investment principle failed", exc)


@router.patch("/{principle_id}", response_model=InvestmentPrincipleDetailResponse, responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def update_investment_principle(principle_id: int, request: InvestmentPrincipleUpdateRequest, service: InvestmentPrincipleService = Depends(_service)):
    try:
        provided = request.model_dump(exclude_unset=True, exclude={"expected_current_version", "sources"})
        sources = None if "sources" not in request.model_fields_set else [_source_payload(source) for source in (request.sources or [])]
        detail = service.update_principle(principle_id, expected_current_version=request.expected_current_version, fields=provided, sources=sources)
        return _to_detail_response(detail, service)
    except InvestmentPrincipleNotFoundError as exc:
        raise _not_found(exc)
    except InvestmentPrincipleConflictError as exc:
        raise _conflict(exc)
    except InvestmentPrincipleValidationError as exc:
        raise _bad_request(exc)
    except InvestmentPrincipleDataIntegrityError as exc:
        raise _internal_error("Update investment principle failed", exc)
    except Exception as exc:
        raise _internal_error("Update investment principle failed", exc)


def _status_endpoint(action: str, method: Any, principle_id: int, request: InvestmentPrincipleStatusActionRequest, service: InvestmentPrincipleService):
    try:
        return _to_detail_response(method(principle_id, expected_status=request.expected_status), service)
    except InvestmentPrincipleNotFoundError as exc:
        raise _not_found(exc)
    except InvestmentPrincipleConflictError as exc:
        raise _conflict(exc)
    except InvestmentPrincipleValidationError as exc:
        raise _bad_request(exc)
    except InvestmentPrincipleDataIntegrityError as exc:
        raise _internal_error(f"{action} investment principle failed", exc)
    except Exception as exc:
        raise _internal_error(f"{action} investment principle failed", exc)


@router.post("/{principle_id}/activate", response_model=InvestmentPrincipleDetailResponse, responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def activate_investment_principle(principle_id: int, request: InvestmentPrincipleStatusActionRequest, service: InvestmentPrincipleService = Depends(_service)):
    return _status_endpoint("Activate", service.activate_principle, principle_id, request, service)


@router.post("/{principle_id}/archive", response_model=InvestmentPrincipleDetailResponse, responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def archive_investment_principle(principle_id: int, request: InvestmentPrincipleStatusActionRequest, service: InvestmentPrincipleService = Depends(_service)):
    return _status_endpoint("Archive", service.archive_principle, principle_id, request, service)


@router.post("/{principle_id}/reject", response_model=InvestmentPrincipleDetailResponse, responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def reject_investment_principle(principle_id: int, request: InvestmentPrincipleStatusActionRequest, service: InvestmentPrincipleService = Depends(_service)):
    return _status_endpoint("Reject", service.reject_principle, principle_id, request, service)


@router.post("/{principle_id}/restore-draft", response_model=InvestmentPrincipleDetailResponse, responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def restore_investment_principle_to_draft(principle_id: int, request: InvestmentPrincipleStatusActionRequest, service: InvestmentPrincipleService = Depends(_service)):
    return _status_endpoint("Restore draft", service.restore_principle_to_draft, principle_id, request, service)


@router.get("/{principle_id}/versions", response_model=InvestmentPrincipleVersionListResponse, responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
def list_investment_principle_versions(principle_id: int, page: int = Query(1), page_size: int = Query(20), service: InvestmentPrincipleService = Depends(_service)):
    try:
        result = service.list_versions(principle_id, page=page, page_size=page_size)
        return InvestmentPrincipleVersionListResponse(
            items=[_to_version_response(version, sources=service.list_version_sources(version.id)) for version in result.items],
            total=result.total, page=result.page, page_size=result.page_size,
        )
    except InvestmentPrincipleNotFoundError as exc:
        raise _not_found(exc)
    except InvestmentPrincipleValidationError as exc:
        raise _bad_request(exc)
    except InvestmentPrincipleDataIntegrityError as exc:
        raise _internal_error("List investment principle versions failed", exc)
    except Exception as exc:
        raise _internal_error("List investment principle versions failed", exc)
