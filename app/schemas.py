from pydantic import BaseModel, ConfigDict, EmailStr
from typing import List, Optional
from datetime import datetime
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# Service 스키마
class ServiceBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "active"
    created_by: Optional[int] = None  # Integer로 변경


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class ServiceResponse(ServiceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# Member 스키마
class MemberBase(BaseModel):
    name: str  # 이름 (필수)
    member_id: str  # 아이디 (필수)
    email: EmailStr  # 이메일 (필수)
    phone: Optional[str] = None  # 연락처
    role: str = "user"  # 역할 (사용자/관리자)
    is_active: bool = True
    description: Optional[str] = None  # 설명 (선택사항)


class MemberCreate(MemberBase):
    password: str  # 비밀번호 (생성시에만 필요)


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    member_id: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None  # 비밀번호 변경
    phone: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    member_id: str
    email: str
    phone: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    description: Optional[str] = None


class MemberDetailResponse(MemberResponse):
    created_services: List['ServiceResponse'] = []


class MemberListResponse(BaseModel):
    members: List[MemberResponse]
    total: int
    page: int
    size: int


# 리스트 응답
class ServiceListResponse(BaseModel):
    services: List[ServiceResponse]
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
