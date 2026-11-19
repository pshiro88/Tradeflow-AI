from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import require_role
from app.core.config import get_settings
from app.db.seed import DEMO_PASSWORD, seed_users
from app.main import app
from app.models.enums import UserRole
from app.models.user import User

# Throwaway routes used only to exercise backend RBAC.
app.add_api_route("/_test/finance-only", lambda: {"ok": True}, dependencies=[Depends(require_role(UserRole.FINANCE))])
app.add_api_route(
    "/_test/operations-only", lambda: {"ok": True}, dependencies=[Depends(require_role(UserRole.OPERATIONS))]
)


@pytest.fixture
def client(db) -> TestClient:
    seed_users(db)
    db.commit()
    return TestClient(app)


def login(client: TestClient, email: str, password: str = DEMO_PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def auth_header(client: TestClient, email: str) -> dict[str, str]:
    token = login(client, email).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- login


@pytest.mark.parametrize(
    ("email", "role"),
    [
        ("admin@example.com", "ADMIN"),
        ("finance@example.com", "FINANCE"),
        ("operations@example.com", "OPERATIONS"),
    ],
)
def test_login_success_returns_token_and_user(client, email, role):
    resp = login(client, email)
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == email
    assert body["user"]["role"] == role
    assert "password" not in str(body).lower()


def test_login_wrong_password_returns_401(client):
    resp = login(client, "admin@example.com", "wrong-password")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_login_unknown_email_returns_same_401_message(client):
    resp = login(client, "nobody@example.com")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_login_email_is_case_insensitive(client):
    assert login(client, "ADMIN@Example.com").status_code == 200


def test_login_inactive_user_returns_401(client, db):
    user = db.scalar(select(User).where(User.email == "finance@example.com"))
    user.is_active = False
    db.commit()
    assert login(client, "finance@example.com").status_code == 401


def test_login_malformed_email_is_rejected_by_validation(client):
    assert login(client, "not-an-email").status_code == 422


def test_passwords_are_stored_hashed_never_plaintext(client, db):
    hashes = db.scalars(select(User.password_hash)).all()
    assert hashes
    for stored in hashes:
        assert stored != DEMO_PASSWORD
        assert stored.startswith("$argon2")


# ---------------------------------------------------------------- authentication


def test_me_without_token_returns_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_with_valid_token_returns_current_user(client):
    resp = client.get("/api/v1/auth/me", headers=auth_header(client, "finance@example.com"))
    assert resp.status_code == 200
    assert resp.json()["email"] == "finance@example.com"
    assert resp.json()["role"] == "FINANCE"


def test_me_with_garbage_token_returns_401(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert resp.status_code == 401


def test_expired_token_returns_401(client, db):
    user = db.scalar(select(User).where(User.email == "admin@example.com"))
    settings = get_settings()
    expired = jwt.encode(
        {"sub": str(user.id), "role": "ADMIN", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_token_signed_with_wrong_secret_returns_401(client, db):
    user = db.scalar(select(User).where(User.email == "admin@example.com"))
    forged = jwt.encode(
        {"sub": str(user.id), "role": "ADMIN", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "some-other-secret-that-is-long-enough-1234567890",
        algorithm="HS256",
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_token_stops_working_when_user_is_deactivated(client, db):
    headers = auth_header(client, "operations@example.com")
    user = db.scalar(select(User).where(User.email == "operations@example.com"))
    user.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_logout_requires_authentication_and_returns_204(client):
    assert client.post("/api/v1/auth/logout").status_code == 401
    resp = client.post("/api/v1/auth/logout", headers=auth_header(client, "admin@example.com"))
    assert resp.status_code == 204


# ---------------------------------------------------------------- authorization (RBAC)


def test_rbac_unauthenticated_gets_401_not_403(client):
    assert client.get("/_test/finance-only").status_code == 401


def test_rbac_matching_role_is_allowed(client):
    resp = client.get("/_test/finance-only", headers=auth_header(client, "finance@example.com"))
    assert resp.status_code == 200


def test_rbac_wrong_role_is_forbidden(client):
    resp = client.get("/_test/finance-only", headers=auth_header(client, "operations@example.com"))
    assert resp.status_code == 403
    resp = client.get("/_test/operations-only", headers=auth_header(client, "finance@example.com"))
    assert resp.status_code == 403


def test_rbac_admin_is_allowed_everywhere(client):
    headers = auth_header(client, "admin@example.com")
    assert client.get("/_test/finance-only", headers=headers).status_code == 200
    assert client.get("/_test/operations-only", headers=headers).status_code == 200
