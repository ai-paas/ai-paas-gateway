from pydantic import BaseModel, ConfigDict, EmailStr, validator
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime
import re

# 타입 체킹할 때만 import (순환 참조 방지)
if TYPE_CHECKING:
    from .service import ServiceResponse

ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Member 스키마
class MemberBase(BaseModel):
    name: str  # 이름 (필수)
    member_id: str  # 아이디 (필수)
    email: EmailStr  # 이메일 (필수)
    phone: Optional[int] = None  # 연락처
    role: str = "user"  # 역할 (사용자/관리자)
    is_active: bool = True
    description: Optional[str] = None  # 설명 (선택사항)


class MemberCreate(MemberBase):
    password: str  # 비밀번호 (생성시에만 필요)
    password_confirm: str  # 비밀번호 확인 추가

    @validator("member_id")
    def validate_member_id(cls, v):
        # 알파벳 소문자 + 숫자 + '-' 조합, 5~45자
        if not re.match(r"^[a-z0-9-]{5,45}$", v):
            raise ValueError("아이디는 알파벳 소문자, 숫자, '-' 조합으로 5~45자여야 합니다.")
        return v

    @validator("password")
    def validate_password(cls, v):
        # 8~16자, 영문 대소문자 + 숫자 + 특수문자 조합
        if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,16}$", v):
            raise ValueError("비밀번호는 8~16자 영문 대소문자, 숫자, 특수문자를 포함해야 합니다.")

        # bcrypt 72바이트 제한 체크 추가
        if len(v.encode('utf-8')) > 72:
            raise ValueError("비밀번호가 너무 깁니다. 더 짧은 비밀번호를 사용해주세요.")

        return v

    @validator("password_confirm")
    def passwords_match(cls, v, values):
        if "password" in values and v != values["password"]:
            raise ValueError("비밀번호와 비밀번호 확인이 일치하지 않습니다.")
        return v

    @validator("phone")
    def validate_phone(cls, v):
        if v and not re.match(r"^\d+$", v):
            raise ValueError("연락처는 숫자만 입력해야 합니다.")
        return v


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    member_id: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None  # 비밀번호 변경
    phone: Optional[int] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    member_id: str
    email: str
    phone: Optional[int] = None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    description: Optional[str] = None


class MemberDetailResponse(MemberResponse):
    created_services: List['ServiceResponse'] = []  # 문자열로 forward reference 사용


class MemberListResponse(BaseModel):
    data: List[MemberResponse]
    total: int
    page: int
    size: int


# 인증 관련 스키마
class LoginRequest(BaseModel):
    member_id: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_EXPIRE_MINUTES * 60  # 초 단위


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str