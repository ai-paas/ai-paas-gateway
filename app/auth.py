from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.cruds import member_crud
from app.database import get_db

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/token")

TOKEN_BLACKLIST = set()


class TokenBlacklistManager:
    @staticmethod
    def add_token(token: str):
        TOKEN_BLACKLIST.add(token)
        return False

    @staticmethod
    def is_token_blacklisted(token: str) -> bool:
        return token in TOKEN_BLACKLIST

    @staticmethod
    def remove_token(token: str):
        TOKEN_BLACKLIST.discard(token)
        return False


class AuthService:
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        pwd_bytes = plain_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))

    @staticmethod
    def get_password_hash(password: str) -> str:
        pwd_bytes = password.encode("utf-8")
        return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt(rounds=12)).decode("utf-8")

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def create_refresh_token(data: dict):
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    @staticmethod
    def verify_token(token: str):
        try:
            if TokenBlacklistManager.is_token_blacklisted(token):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked",
                )

            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            member_id: str = payload.get("sub")
            token_type: str = payload.get("type")

            if member_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token",
                )

            return {"member_id": member_id, "type": token_type}
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

    @staticmethod
    def authenticate_member(db: Session, member_id: str, password: str):
        member = member_crud.get_member(db, member_id)
        if not member:
            return False
        if not AuthService.verify_password(password, member.password_hash):
            return False
        return member

    @staticmethod
    def revoke_token(token: str):
        TokenBlacklistManager.add_token(token)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    token_data = AuthService.verify_token(token)

    if token_data["type"] != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    member = member_crud.get_member(db, token_data["member_id"])
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return member


def get_current_admin_user(current_user=Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def verify_member_access(current_user, target_member_id: str):
    if current_user.member_id != target_member_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )


def verify_admin_access(current_user):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


class MemberAccessChecker:
    def __init__(self, member_id_param: str = "member_id"):
        self.member_id_param = member_id_param

    def __call__(self, current_user=Depends(get_current_user)):
        def check_access(target_member_id: str):
            verify_member_access(current_user, target_member_id)
            return current_user

        return check_access


def check_member_access(current_user, member_id: str):
    verify_member_access(current_user, member_id)
    return current_user
