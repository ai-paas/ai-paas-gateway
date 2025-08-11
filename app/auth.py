import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.crud import member_crud
from app.config import settings

# 비밀번호 해싱 설정
HASH_SCHEMES = os.getenv("PASSWORD_HASH_SCHEMES", "bcrypt").split(",")
pwd_context = CryptContext(schemes=HASH_SCHEMES, deprecated="auto")

# Bearer 토큰 스키마
security = HTTPBearer()

# 토큰 블랙리스트 (실제 운영환경에서는 Redis 등 사용)
TOKEN_BLACKLIST = set()


class TokenBlacklistManager:
    """토큰 블랙리스트 관리 클래스"""

    @staticmethod
    def add_token(token: str):
        # 인메모리 블랙리스트 사용
        TOKEN_BLACKLIST.add(token)
        return False

    @staticmethod
    def is_token_blacklisted(token: str) -> bool:
        # 인메모리 블랙리스트 확인
        return token in TOKEN_BLACKLIST

    @staticmethod
    def remove_token(token: str):
        TOKEN_BLACKLIST.discard(token)
        return False

class AuthService:
    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """비밀번호 검증"""
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        """비밀번호 해싱"""
        return pwd_context.hash(password)

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
        """액세스 토큰 생성"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return encoded_jwt

    @staticmethod
    def create_refresh_token(data: dict):
        """리프레시 토큰 생성"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
        to_encode.update({"exp": expire, "type": "refresh"})
        encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return encoded_jwt

    @staticmethod
    def verify_token(token: str):
        """토큰 검증"""
        try:
            # 블랙리스트 확인
            if TokenBlacklistManager.is_token_blacklisted(token):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked"
                )

            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            member_id: str = payload.get("sub")
            token_type: str = payload.get("type")

            if member_id is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token"
                )

            return {"member_id": member_id, "type": token_type}

        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )

    @staticmethod
    def authenticate_member(db: Session, member_id: str, password: str):
        """사용자 인증"""
        member = member_crud.get_member(db, member_id)
        if not member:
            return False
        if not AuthService.verify_password(password, member.password_hash):
            return False
        return member

    @staticmethod
    def revoke_token(token: str):
        """토큰 무효화 (로그아웃)"""
        TokenBlacklistManager.add_token(token)


# 의존성: 현재 사용자 가져오기
def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: Session = Depends(get_db)
):
    """현재 인증된 사용자 정보 반환"""
    token = credentials.credentials
    token_data = AuthService.verify_token(token)

    if token_data["type"] != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type"
        )

    member = member_crud.get_member(db, token_data["member_id"])
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    return member


# 의존성: 관리자 권한 확인
def get_current_admin_user(current_user=Depends(get_current_user)):
    """현재 사용자가 관리자인지 확인"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


# 권한 검증 헬퍼 함수들
def verify_member_access(current_user, target_member_id: str):
    """멤버 접근 권한 확인 (본인 또는 관리자)"""
    if current_user.member_id != target_member_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )


def verify_admin_access(current_user):
    """관리자 권한 확인"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )


# 동적 권한 검증을 위한 의존성 팩토리
class MemberAccessChecker:
    """특정 멤버에 대한 접근 권한을 확인하는 의존성 클래스"""

    def __init__(self, member_id_param: str = "member_id"):
        self.member_id_param = member_id_param

    def __call__(self, current_user=Depends(get_current_user)):
        # 이 함수는 실제 요청 시 member_id를 받아서 권한을 확인할 수 있도록 하는 팩토리
        def check_access(target_member_id: str):
            verify_member_access(current_user, target_member_id)
            return current_user

        return check_access


# 편의를 위한 권한 검증 헬퍼
def check_member_access(current_user, member_id: str):
    """멤버 접근 권한을 확인하고 사용자 정보 반환"""
    verify_member_access(current_user, member_id)
    return current_user