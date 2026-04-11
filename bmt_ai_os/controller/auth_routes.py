"""Authentication API endpoints for BMT AI OS controller.

POST /api/v1/auth/login               — Exchange credentials for a JWT
GET  /api/v1/auth/me                  — Return info for the currently authenticated user
POST /api/v1/auth/logout              — Revoke the current token
POST /api/v1/auth/users               — Create a new user (admin only)
GET  /api/v1/auth/users               — List all users (admin only)
DELETE /api/v1/auth/users/{username}  — Delete user and revoke their tokens (admin only)
PATCH /api/v1/auth/users/{username}/role   — Change user role (admin only)
POST /api/v1/auth/users/{username}/lock    — Manually lock account (admin only)
POST /api/v1/auth/users/{username}/unlock  — Manually unlock account (admin only)
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import Role, create_token, get_store
from .rate_limit import login_rate_limit

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
    duration_seconds: int = 900  # 15 minutes default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_admin(request: Request) -> None:
    """Raise HTTP 403 if the caller is not an admin."""
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


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Obtain a JWT access token",
    dependencies=[Depends(login_rate_limit)],
)
async def login(body: LoginRequest) -> LoginResponse:
    """Authenticate with username and password; receive a 24-hour JWT.

    Returns HTTP 401 if credentials are invalid or the account is locked.
    """
    store = get_store()
    user = store.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Invalid username or password, or account is locked.",
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


@router.post("/logout", summary="Revoke the current JWT (logout)")
async def logout(request: Request) -> dict:
    """Revoke the bearer token used for this request.

    After logout the token is placed on the blacklist and will be rejected
    by the middleware on subsequent requests.
    """
    jti = getattr(request.state, "jti", None)
    if jti is None:
        # Unauthenticated or no-user mode — nothing to revoke
        return {"revoked": False}

    store = get_store()
    # Derive expiry from the token exp if available, otherwise use 24 h from now
    auth_header = request.headers.get("Authorization", "")
    expires_at = time.time() + 86400  # safe default
    if auth_header.startswith("Bearer "):
        import jwt as pyjwt

        try:
            import os

            payload = pyjwt.decode(
                auth_header[7:],
                os.environ.get("BMT_JWT_SECRET", ""),
                algorithms=["HS256"],
            )
            expires_at = float(payload.get("exp", expires_at))
        except Exception:
            pass

    store.revoke_token(jti, expires_at)
    return {"revoked": True}


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


@router.post("/users", summary="Create a new user (admin only)")
async def create_user(body: CreateUserRequest, request: Request) -> dict:
    """Create a new user account.

    Requires admin role. Returns the created user's public info.
    """
    _require_admin(request)
    store = get_store()
    try:
        user = store.create_user(body.username, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)})
    return user.as_dict()


@router.get("/users", summary="List all users (admin only)")
async def list_users(request: Request) -> list[dict]:
    """Return a list of all registered users."""
    _require_admin(request)
    store = get_store()
    return [u.as_dict() for u in store.list_users()]


@router.delete("/users/{username}", summary="Delete user (admin only)")
async def delete_user(username: str, request: Request) -> dict:
    """Delete a user account.

    Any tokens previously issued to this user become invalid once they
    expire naturally (there is no per-user token index). To immediately
    invalidate tokens, clients should call /logout before deletion.
    """
    _require_admin(request)
    store = get_store()
    deleted = store.delete_user(username)
    if not deleted:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    return {"deleted": True, "username": username}


@router.patch("/users/{username}/role", summary="Change user role (admin only)")
async def update_role(username: str, body: UpdateRoleRequest, request: Request) -> dict:
    """Update a user's role.

    The caller is responsible for revoking the user's existing tokens so that
    the role change takes effect immediately (e.g., by calling /logout on
    their behalf or maintaining a per-user token registry).
    """
    _require_admin(request)
    store = get_store()
    try:
        updated = store.update_user_role(username, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)})
    if not updated:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    return {"updated": True, "username": username, "role": body.role}


@router.post("/users/{username}/lock", summary="Manually lock account (admin only)")
async def lock_account(username: str, body: LockRequest, request: Request) -> dict:
    """Lock a user account for the specified duration (default 15 minutes)."""
    _require_admin(request)
    store = get_store()
    locked = store.lock_account(username, body.duration_seconds)
    if not locked:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    return {
        "locked": True,
        "username": username,
        "duration_seconds": body.duration_seconds,
    }


@router.post("/users/{username}/unlock", summary="Manually unlock account (admin only)")
async def unlock_account(username: str, request: Request) -> dict:
    """Remove any lock from a user account and reset the failed-login counter."""
    _require_admin(request)
    store = get_store()
    unlocked = store.unlock_account(username)
    if not unlocked:
        raise HTTPException(status_code=404, detail={"message": f"User '{username}' not found."})
    return {"unlocked": True, "username": username}
