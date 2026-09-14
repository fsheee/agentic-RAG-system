"""Auth endpoints and the get_current_user dependency.

Role/user identity always comes from the signed JWT, never from the
request body. Clients cannot assign themselves a role at registration.
"""

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Session, select

from app.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db import get_session
from app.schema import Role, User

router = APIRouter(prefix="/auth", tags=["auth"])

_bearer = HTTPBearer()

# Who may create which roles via POST /auth/users. Patients self-register
# via /auth/register (always patient); admins come from controlled setup
# (seed/ops), never from the API.
CREATION_RULES: dict[Role, set[Role]] = {
    Role.admin: {Role.employee, Role.doctor, Role.hr},
    Role.hr: {Role.employee},
}


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: Role
    is_active: bool


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (pyjwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*allowed_roles: Role):
    """Dependency factory: allow only users whose JWT role is in the list.

    Roles are always taken from the token/DB, never from the request.
    """

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Insufficient permissions"
            )
        return user

    return checker


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(request: RegisterRequest, session: Session = Depends(get_session)):
    existing = session.exec(
        select(User).where(User.email == request.email)
    ).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user = User(
        name=request.name,
        email=request.email,
        password_hash=hash_password(request.password),
        # New users are patients; roles are only assigned by admins.
        role=Role.patient,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == request.email)).first()
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")

    return TokenResponse(access_token=create_access_token(user.id, user.role.value))


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    request: CreateUserRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Internal user creation: admin/HR assign staff roles.

    The new user's role comes from this request, but only after the
    caller's own role (from their JWT) has been checked against
    CREATION_RULES. Patients can never be created here — they register
    themselves — and admins are never created via the API.
    """
    allowed = CREATION_RULES.get(user.role, set())
    if request.role not in allowed:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You do not have permission to create users with this role",
        )

    existing = session.exec(
        select(User).where(User.email == request.email)
    ).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    new_user = User(
        name=request.name,
        email=request.email,
        password_hash=hash_password(request.password),
        role=request.role,
        is_active=True,
    )
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    return new_user


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return user
