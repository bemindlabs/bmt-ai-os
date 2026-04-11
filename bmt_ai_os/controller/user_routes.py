"""User management API at /api/v1/users — shorter-path aliases for the admin
user-management endpoints that live under /api/v1/auth/users.

These routes expose the same handlers as auth_routes but at the conventional
REST path /api/v1/users so that operator tooling and E2E tests can use a
predictable, short URL without the /auth/ prefix.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .auth_routes import (
    CreateUserRequest,
    LockRequest,
    UpdateRoleRequest,
    create_user,
    delete_user,
    list_users,
    lock_account,
    unlock_account,
    update_role,
)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.post("", status_code=201, summary="Create a new user (admin only)")
async def create_user_alias(body: CreateUserRequest, request: Request) -> dict:
    """Alias for POST /api/v1/auth/users."""
    return await create_user(body, request)


@router.get("", summary="List all users (admin only)")
async def list_users_alias(request: Request) -> list[dict]:
    """Alias for GET /api/v1/auth/users."""
    return await list_users(request)


@router.delete("/{username}", summary="Delete user (admin only)")
async def delete_user_alias(username: str, request: Request) -> dict:
    """Alias for DELETE /api/v1/auth/users/{username}."""
    return await delete_user(username, request)


@router.patch("/{username}/role", summary="Change user role (admin only)")
async def update_role_alias(username: str, body: UpdateRoleRequest, request: Request) -> dict:
    """Alias for PATCH /api/v1/auth/users/{username}/role."""
    return await update_role(username, body, request)


@router.post("/{username}/lock", summary="Manually lock account (admin only)")
async def lock_account_alias(username: str, body: LockRequest, request: Request) -> dict:
    """Alias for POST /api/v1/auth/users/{username}/lock."""
    return await lock_account(username, body, request)


@router.post("/{username}/unlock", summary="Manually unlock account (admin only)")
async def unlock_account_alias(username: str, request: Request) -> dict:
    """Alias for POST /api/v1/auth/users/{username}/unlock."""
    return await unlock_account(username, request)
