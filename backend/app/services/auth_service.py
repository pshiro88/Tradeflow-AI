import uuid

import jwt
from sqlalchemy.orm import Session

from app.core.security import create_access_token, decode_access_token, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse, UserOut


class AuthenticationError(Exception):
    """Credentials or token were invalid. The message is safe to show to the client."""


class AuthService:
    def __init__(self, db: Session) -> None:
        self.users = UserRepository(db)

    def login(self, email: str, password: str) -> TokenResponse:
        user = self.users.get_by_email(email)
        password_ok = verify_password(password, user.password_hash if user else None)
        # One error for unknown email, wrong password and disabled account (no user enumeration).
        if user is None or not password_ok or not user.is_active:
            raise AuthenticationError("Invalid email or password")
        token, expires_in = create_access_token(user.id, user.role.value)
        return TokenResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))

    def user_from_token(self, token: str) -> User:
        try:
            payload = decode_access_token(token)
            user_id = uuid.UUID(payload["sub"])
        except (jwt.PyJWTError, KeyError, ValueError) as exc:
            raise AuthenticationError("Invalid or expired token") from exc
        user = self.users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid or expired token")
        return user
