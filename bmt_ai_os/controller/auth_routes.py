"""Authentication API endpoints for BMT AI OS controller.

POST /api/v1/auth/login              — Exchange credentials for a JWT
POST /api/v1/auth/logout             — Revoke the current JWT
GET  /api/v1/auth/me                 — Return info for the currently authenticated user
GET  /api/v1/auth/users              — List all users (admin only)
POST /api/v1/auth/users              — Create a user (admin only)
DELETE /api/v1/auth/users/{username} — Delete a user (admin only)
PATCH  /api/v1/auth/users/{username}/role   — Update a user's role (admin only)
POST   /api/v1/auth/users/{username}/lock   — Lock a user account (admin only)
POST   /api/v1/auth/users/{username}/unlock — Unlock a user account (admin only)
"""

from __future__ import annotations

import logging

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import Role, create_token, get_store, revoke_token
from .rate_limit import login_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class MeResponse(BaseModel):
    username: str
    role: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UpdateRoleRequest(BaseModel):
    role: str


class LockRequest(BaseModel):
    duration_seconds: int = 900


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Obtain a JWT access token",
    dependencies=[Depends(login_rate_limit)],
)
async def login(body: LoginRequest) -> LoginResponse:
    """Authenticate with username and password; receive a 24-hour JWT.

    Returns HTTP 401 if credentials are invalid.
    """
    store = get_store()
    user = store.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Invalid username or password.",
                "type": "authentication_error",
                "code": "invalid_credentials",
            },
        )

    token = create_token(user)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        role=user.role.value,
        username=user.username,
    )


@router.post("/logout", summary="Revoke the current JWT access token")
async def logout(request: Request) -> dict:
    """Revoke the bearer token presented in the Authorization header.

    After this call the token will be rejected by the auth middleware even if
    it has not yet expired.  Returns HTTP 400 when no valid token is provided.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No Bearer token found in Authorization header.",
                "type": "invalid_request_error",
                "code": "missing_token",
            },
        )
    token = auth_header[7:]
    store = get_store()
    try:
        revoke_token(token, store=store)
    except (jwt.PyJWTError, ValueError) as exc:
        logger.warning("Logout failed — could not revoke token: %s", exc)
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Could not revoke token: {exc}",
                "type": "invalid_request_error",
                "code": "invalid_token",
            },
        )
    return {"revoked": True, "message": "Token revoked successfully."}


@router.get("/me", response_model=MeResponse, summary="Current authenticated user")
async def me(request: Request) -> MeResponse:
    """Return the username and role from the authenticated JWT.

    Requires a valid ``Authorization: Bearer <token>`` header.
    Returns HTTP 401 when no user context is present (unauthenticated access
    on an instance with no registered users).
    """
    username = getattr(request.state, "user", None)
    role = getattr(request.state, "role", None)

    if username is None:
        # No users registered — reflect anonymous access
        return MeResponse(username="anonymous", role=Role.admin.value)

    return MeResponse(username=username, role=role)


# ---------------------------------------------------------------------------
# User management (admin only)
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


@router.get("/users", summary="List all users (admin only)")
async def list_users(request: Request) -> list:
    """Return all registered users (without password hashes).

    Requires admin role.
    """
    _require_admin(request)
    store = get_store()
    return [u.as_dict() for u in store.list_users()]


@router.post("/users", status_code=201, summary="Create a new user (admin only)")
async def create_user(body: CreateUserRequest, request: Request) -> dict:
    """Create a new user account.

    Requires admin role.
    """
    _require_admin(request)
    store = get_store()
    try:
        user = store.create_user(body.username, body.password, body.role)
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail={"message": msg})
        raise HTTPException(status_code=400, detail={"message": msg})
    return user.as_dict()


@router.delete("/users/{username}", summary="Delete a user (admin only)")
async def delete_user(username: str, request: Request) -> dict:
    """Delete a user account.

    Requires admin role.
    """
    _require_admin(request)
    store = get_store()
    deleted = store.delete_user(username)
    if not deleted:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    return {"deleted": True, "username": username}


@router.patch("/users/{username}/role", summary="Update a user's role (admin only)")
async def update_role(username: str, body: UpdateRoleRequest, request: Request) -> dict:
    """Update the RBAC role for a user.

    Requires admin role.
    """
    _require_admin(request)
    store = get_store()
    try:
        updated = store.update_user_role(username, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)})
    if not updated:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    user = store.get_user(username)
    return {"username": username, "role": user.role.value if user else body.role}


@router.post("/users/{username}/lock", summary="Lock a user account (admin only)")
async def lock_user(username: str, body: LockRequest, request: Request) -> dict:
    """Lock a user account for the specified duration.

    Requires admin role.
    """
    _require_admin(request)
    store = get_store()
    locked = store.lock_account(username, duration_seconds=body.duration_seconds)
    if not locked:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    return {"locked": True, "username": username, "duration_seconds": body.duration_seconds}


@router.post("/users/{username}/unlock", summary="Unlock a user account (admin only)")
async def unlock_user(username: str, request: Request) -> dict:
    """Unlock a previously locked user account.

    Requires admin role.
    """
    _require_admin(request)
    store = get_store()
    unlocked = store.unlock_account(username)
    if not unlocked:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    return {"unlocked": True, "username": username}
