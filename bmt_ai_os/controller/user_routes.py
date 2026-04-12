"""User management API endpoints for BMT AI OS controller.

Provides user CRUD at /api/v1/users (admin only).

GET    /api/v1/users                   — List all users
POST   /api/v1/users                   — Create a user
DELETE /api/v1/users/{username}        — Delete a user
PATCH  /api/v1/users/{username}/role   — Update a user's role
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .auth import Role, get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UpdateRoleRequest(BaseModel):
    role: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_admin(request: Request) -> None:
    """Raise 403 if the requesting user is not an admin."""
    role = getattr(request.state, "role", None)
    if role != Role.admin.value:
        raise HTTPException(
            status_code=403,
            detail={
                "message": "Admin role required.",
                "type": "authorization_error",
                "code": "forbidden",
            },
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", summary="List all users (admin only)")
async def list_users(request: Request) -> list:
    """Return all registered users (without password hashes). Requires admin role."""
    _require_admin(request)
    store = get_store()
    return [u.as_dict() for u in store.list_users()]


@router.post("", status_code=201, summary="Create a new user (admin only)")
async def create_user(body: CreateUserRequest, request: Request) -> dict:
    """Create a new user account. Requires admin role."""
    _require_admin(request)
    store = get_store()
    try:
        user = store.create_user(body.username, body.password, body.role)
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail={"message": msg}) from exc
        raise HTTPException(status_code=400, detail={"message": msg}) from exc
    return user.as_dict()


@router.delete("/{username}", summary="Delete a user (admin only)")
async def delete_user(username: str, request: Request) -> dict:
    """Delete a user account. Requires admin role."""
    _require_admin(request)
    store = get_store()
    deleted = store.delete_user(username)
    if not deleted:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    return {"deleted": True, "username": username}


@router.patch("/{username}/role", summary="Update a user's role (admin only)")
async def update_role(username: str, body: UpdateRoleRequest, request: Request) -> dict:
    """Update the RBAC role for a user. Requires admin role."""
    _require_admin(request)
    store = get_store()
    try:
        updated = store.update_user_role(username, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc
    if not updated:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    user = store.get_user(username)
    return {"username": username, "role": user.role.value if user else body.role}
