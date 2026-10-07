"""Fighters catalog API router."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ufc_api.core.errors import DomainError, ErrorDetail
from ufc_api.data.parquet_catalog import resolve_canonical_fighter_id
from ufc_api.db.session import get_optional_db_session
from ufc_api.fighters.repository import FighterCatalogRepository
from ufc_api.fighters.schemas import FighterDetail, FighterPage
from ufc_api.fighters.standouts import division_standouts
from ufc_api.fights.schemas import FighterHistoryPage

router = APIRouter(prefix="/api/v1/fighters", tags=["fighters"])


@router.get("/standouts", summary="Historical division form board")
async def get_division_standouts() -> dict:
    """Rank accepted recent divisional records; this is not an official UFC ranking."""
    return division_standouts()


@router.get("", response_model=FighterPage, summary="List canonical fighters")
async def list_fighters(
    session: Annotated[AsyncSession | None, Depends(get_optional_db_session)] = None,
    query: Annotated[
        str | None,
        Query(
            description="Search query on display name (2-100 characters)",
            min_length=2,
            max_length=100,
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1-100)")] = 25,
    cursor: Annotated[str | None, Query(description="Keyset pagination cursor")] = None,
) -> FighterPage:
    """Return keyset-paginated canonical fighters with optional search filtering."""
    if query is not None and len(query.strip()) < 2:
        raise DomainError(
            code="invalid_query",
            message="Search query must contain at least 2 non-whitespace characters.",
            status_code=422,
            details=[ErrorDetail(field="query", reason="minimum 2 characters required")],
        )
    repo = FighterCatalogRepository(session)
    return await repo.list_fighters(query=query, limit=limit, cursor=cursor)


@router.get(
    "/{fighter_id}",
    response_model=FighterDetail,
    summary="Get canonical fighter profile and aliases",
    responses={404: {"description": "Fighter not found"}},
)
async def get_fighter(
    fighter_id: str,
    session: Annotated[AsyncSession | None, Depends(get_optional_db_session)] = None,
) -> FighterDetail:
    """Return canonical fighter details, including reviewed aliases and status."""
    resolved_id = resolve_canonical_fighter_id(fighter_id)
    repo = FighterCatalogRepository(session)
    fighter = await repo.get_fighter(resolved_id)
    if fighter is None:
        raise DomainError(
            code="fighter_not_found",
            message=f"Fighter {fighter_id} was not found in the canonical catalog.",
            status_code=404,
            details=[
                ErrorDetail(field="fighter_id", reason="no canonical fighter matches this ID")
            ],
        )
    return fighter


@router.get(
    "/{fighter_id}/history",
    response_model=FighterHistoryPage,
    summary="Get fighter bout history",
    responses={404: {"description": "Fighter not found"}},
)
async def get_fighter_history(
    fighter_id: str,
    session: Annotated[AsyncSession | None, Depends(get_optional_db_session)] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1-100)")] = 25,
    cursor: Annotated[str | None, Query(description="Keyset pagination cursor")] = None,
) -> FighterHistoryPage:
    """Return keyset-paginated historical bouts participated in by the canonical fighter."""
    resolved_id = resolve_canonical_fighter_id(fighter_id)
    repo = FighterCatalogRepository(session)
    history = await repo.get_fighter_history(resolved_id, limit=limit, cursor=cursor)
    if history is None:
        raise DomainError(
            code="fighter_not_found",
            message=f"Fighter {fighter_id} was not found in the canonical catalog.",
            status_code=404,
            details=[
                ErrorDetail(field="fighter_id", reason="no canonical fighter matches this ID")
            ],
        )
    return history
