"""Authentication and user-management API endpoints for BMT AI OS controller.

POST   /api/v1/auth/login           — Exchange credentials for a JWT
GET    /api/v1/auth/me              — Return info for the currently authenticated user

Admin-only user management:
GET    /api/v1/users                — List all users
POST   /api/v1/users                — Create a new user
PATCH  /api/v1/users/{username}/role — Update a user's role
DELETE /api/v1/users/{username}     — Delete a user
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator

from .auth import Role, create_token, get_store, require_role

router = APIRouter(tags=["auth"])


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
    role: str = Role.viewer.value

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid = [r.value for r in Role]
        if v not in valid:
            raise ValueError(f"Invalid role '{v}'. Must be one of: {valid}")
        return v


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: str


class UpdateRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid = [r.value for r in Role]
        if v not in valid:
            raise ValueError(f"Invalid role '{v}'. Must be one of: {valid}")
        return v


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/auth/login",
    response_model=LoginResponse,
    summary="Obtain a JWT access token",
)
async def login(body: LoginRequest) -> LoginResponse:
    """Authenticate with username and password; receive a 24-hour JWT.

    Returns HTTP 401 if credentials are invalid.
    """
    store = get_store()
    user = store.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
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


@router.get(
    "/api/v1/auth/me",
    response_model=MeResponse,
    summary="Current authenticated user",
)
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
# User management endpoints (admin-only)
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/users",
    response_model=list[UserResponse],
    summary="List all users (admin only)",
)
async def list_users(
    _current: dict = Depends(require_role(Role.admin)),
) -> list[UserResponse]:
    """Return all registered users. Requires admin role."""
    store = get_store()
    return [UserResponse(**u.as_dict()) for u in store.list_users()]


@router.post(
    "/api/v1/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (admin only)",
)
async def create_user(
    body: CreateUserRequest,
    _current: dict = Depends(require_role(Role.admin)),
) -> UserResponse:
    """Create a new user with the specified role. Requires admin role."""
    store = get_store()
    try:
        user = store.create_user(body.username, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "type": "conflict_error",
                "code": "user_exists",
            },
        )
    return UserResponse(**user.as_dict())


@router.patch(
    "/api/v1/users/{username}/role",
    response_model=UserResponse,
    summary="Update a user's role (admin only)",
)
async def update_user_role(
    username: str,
    body: UpdateRoleRequest,
    _current: dict = Depends(require_role(Role.admin)),
) -> UserResponse:
    """Change the role of an existing user. Requires admin role."""
    store = get_store()
    updated = store.update_user_role(username, body.role)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": f"User '{username}' not found.",
                "type": "not_found_error",
                "code": "user_not_found",
            },
        )
    user = store.get_user(username)
    return UserResponse(**user.as_dict())


@router.delete(
    "/api/v1/users/{username}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user (admin only)",
)
async def delete_user(
    username: str,
    current: dict = Depends(require_role(Role.admin)),
) -> None:
    """Delete a user by username. Requires admin role.

    An admin cannot delete their own account to prevent lockout.
    """
    if username == current.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "Cannot delete your own account.",
                "type": "bad_request_error",
                "code": "self_delete_forbidden",
            },
        )

    store = get_store()
    deleted = store.delete_user(username)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": f"User '{username}' not found.",
                "type": "not_found_error",
                "code": "user_not_found",
            },
        )
