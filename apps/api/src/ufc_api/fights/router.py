"""Fights catalog API router."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ufc_api.core.errors import DomainError, ErrorDetail
from ufc_api.db.session import get_optional_db_session
from ufc_api.fights.repository import FightCatalogRepository
from ufc_api.fights.schemas import FightDetail, FightPage

router = APIRouter(prefix="/api/v1/fights", tags=["fights"])


@router.get(
    "",
    response_model=FightPage,
    summary="List canonical fights with optional filters",
)
async def list_fights(
    session: Annotated[AsyncSession | None, Depends(get_optional_db_session)] = None,
    division: Annotated[str | None, Query(description="Filter by division code")] = None,
    status: Annotated[str | None, Query(description="Filter by fight status")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Page size (1-100)")] = 25,
    cursor: Annotated[str | None, Query(description="Keyset pagination cursor")] = None,
) -> FightPage:
    """Return keyset-paginated canonical fights with optional division and status filtering."""
    repo = FightCatalogRepository(session)
    return await repo.list_fights(division=division, status=status, limit=limit, cursor=cursor)


@router.get(
    "/{fight_id}",
    response_model=FightDetail,
    summary="Get canonical fight details",
    responses={404: {"description": "Fight not found"}},
)
async def get_fight(
    fight_id: UUID,
    session: Annotated[AsyncSession | None, Depends(get_optional_db_session)] = None,
) -> FightDetail:
    """Return canonical fight details, participants, outcome, and source references."""
    repo = FightCatalogRepository(session)
    fight = await repo.get_fight(fight_id)
    if fight is None:
        raise DomainError(
            code="fight_not_found",
            message=f"Fight {fight_id} was not found in the canonical catalog.",
            status_code=404,
            details=[ErrorDetail(field="fight_id", reason="no canonical fight matches this ID")],
        )
    return fight
