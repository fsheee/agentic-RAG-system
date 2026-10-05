import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from app import api
from app.auth import create_access_token, hash_password
from app.db import get_session
from app.schema import Role, User


@pytest.fixture()
def client():
    # In-memory SQLite so auth tests don't need live Neon. StaticPool keeps
    # a single shared connection so the schema persists across sessions.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def test_session():
        with Session(engine) as session:
            yield session

    test_client = TestClient(api.app)
    api.app.dependency_overrides[get_session] = test_session
    yield test_client
    api.app.dependency_overrides.clear()


REGISTER = {
    "name": "Ayesha Khan",
    "email": "ayesha@example.com",
    "password": "supersecret1",
}


def test_register_success(client):
    response = client.post("/auth/register", json=REGISTER)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == REGISTER["email"]
    assert body["role"] == "patient"
    assert body["is_active"] is True
    assert "password_hash" not in body


def test_register_duplicate_email(client):
    client.post("/auth/register", json=REGISTER)
    response = client.post("/auth/register", json=REGISTER)

    assert response.status_code == 409


def test_login_success(client):
    client.post("/auth/register", json=REGISTER)

    response = client.post(
        "/auth/login",
        json={"email": REGISTER["email"], "password": REGISTER["password"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    payload = pyjwt.decode(
        body["access_token"], options={"verify_signature": False}
    )
    assert payload["role"] == "patient"


def test_login_wrong_password(client):
    client.post("/auth/register", json=REGISTER)

    response = client.post(
        "/auth/login",
        json={"email": REGISTER["email"], "password": "wrongpass123"},
    )

    assert response.status_code == 401


def _add_user(session, email="ali@example.com", role=Role.doctor, **overrides) -> User:
    user = User(
        name="Dr. Ali",
        email=email,
        password_hash=hash_password("password123"),
        role=role,
        **overrides,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _users_me(client, token: str):
    return client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})


def test_invalid_jwt_rejected(client):
    response = _users_me(client, "not.a.jwt")

    assert response.status_code == 401


def test_missing_user_rejected(client):
    # Valid signature, but user id 999 does not exist.
    token = create_access_token(999, "patient")

    response = _users_me(client, token)

    assert response.status_code == 401


def test_inactive_user_rejected(client):
    # Create an inactive user directly, then use its (valid) token.
    with next(api.app.dependency_overrides[get_session]()) as session:
        user = _add_user(session, is_active=False)
    token = create_access_token(user.id, user.role.value)

    response = _users_me(client, token)

    assert response.status_code == 401


def _login_as(client, session, **overrides):
    user = _add_user(session, email=f"{overrides.get('role', 'doctor')}1@example.com", **overrides)
    token = create_access_token(user.id, user.role.value)
    return token


CREATE_USER = {
    "name": "New Staff",
    "email": "newstaff@example.com",
    "password": "supersecret1",
}


def _create_user(client, token, role, email="newstaff@example.com"):
    return client.post(
        "/auth/users",
        json={**CREATE_USER, "email": email, "role": role},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_admin_creates_doctor(client):
    with next(api.app.dependency_overrides[get_session]()) as session:
        token = _login_as(client, session, role=Role.admin)

    response = _create_user(client, token, "doctor")

    assert response.status_code == 201
    assert response.json()["role"] == "doctor"
    assert "password_hash" not in response.json()


def test_admin_creates_hr_and_employee(client):
    with next(api.app.dependency_overrides[get_session]()) as session:
        token = _login_as(client, session, role=Role.admin)

    assert _create_user(client, token, "hr").status_code == 201
    assert _create_user(client, token, "employee", "newemployee@example.com").status_code == 201


def test_admin_cannot_create_admin(client):
    # Admins come from controlled setup (seed), never from the API.
    with next(api.app.dependency_overrides[get_session]()) as session:
        token = _login_as(client, session, role=Role.admin)

    assert _create_user(client, token, "admin").status_code == 403


def test_hr_creates_employee_only(client):
    with next(api.app.dependency_overrides[get_session]()) as session:
        token = _login_as(client, session, role=Role.hr)

    assert _create_user(client, token, "employee").status_code == 201
    assert _create_user(client, token, "doctor").status_code == 403
    assert _create_user(client, token, "hr").status_code == 403


def test_patient_and_doctor_cannot_create_users(client):
    for role in (Role.patient, Role.doctor, Role.employee):
        with next(api.app.dependency_overrides[get_session]()) as session:
            token = _login_as(client, session, role=role)

        assert _create_user(client, token, "employee").status_code == 403


def test_create_user_requires_auth(client):
    response = client.post("/auth/users", json={**CREATE_USER, "role": "employee"})

    assert response.status_code == 401


def test_create_user_duplicate_email(client):
    with next(api.app.dependency_overrides[get_session]()) as session:
        admin_token = _login_as(client, session, role=Role.admin)
        _add_user(session, email=CREATE_USER["email"])

    response = _create_user(client, admin_token, "employee")

    assert response.status_code == 409
