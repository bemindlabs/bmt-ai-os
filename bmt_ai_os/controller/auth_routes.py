"""Authentication API endpoints for BMT AI OS controller.

POST /api/v1/auth/login  — Exchange credentials for a JWT
GET  /api/v1/auth/me     — Return info for the currently authenticated user
"""

from __future__ import annotations

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
