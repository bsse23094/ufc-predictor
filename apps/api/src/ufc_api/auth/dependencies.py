"""Authentication and authorization dependencies for the API.

Provides API-key-based role checking for public, analyst, and admin boundaries.
OIDC/JWT auth is documented in the architecture but deferred until production;
these key-based guards satisfy M7 acceptance for local/staging environments.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal

from fastapi import Depends, Header, Request

from ufc_api.core.config import Settings, get_settings
from ufc_api.core.errors import DomainError

Role = Literal["public", "analyst", "data_operator", "model_manager", "admin"]


def _resolve_role(api_key: str | None, settings: Settings) -> Role:
    """Map an API key to its highest role, or return public."""
    if not api_key:
        return "public"

    admin_keys = {k.strip() for k in settings.admin_api_keys.split(",") if k.strip()}
    if api_key in admin_keys:
        return "admin"

    analyst_keys = {k.strip() for k in settings.analyst_api_keys.split(",") if k.strip()}
    if api_key in analyst_keys:
        return "analyst"

    return "public"


async def get_current_role(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Role:
    """Extract the caller's role from the API key header."""
    settings: Settings = getattr(request.app.state, "settings", get_settings())
    role = _resolve_role(x_api_key, settings)
    request.state.role = role
    return role


def require_role(*allowed_roles: Role) -> Callable[..., Coroutine[Any, Any, Role]]:
    """Return a dependency that rejects requests whose role is not in the allow-list."""

    async def _check(
        role: Annotated[Role, Depends(get_current_role)],
    ) -> Role:
        if role not in allowed_roles:
            raise DomainError(
                code="forbidden",
                message="Insufficient permissions for this endpoint.",
                status_code=403,
            )
        return role

    return _check
