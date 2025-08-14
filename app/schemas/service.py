from pydantic import BaseModel, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime

ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Service 스키마
class ServiceBase(BaseModel):
    name: str
    description: Optional[str] = None
    tag: Optional[str] = None


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tag: Optional[str] = None


class CreatorInfo(BaseModel):
    id: int
    name: str
    member_id: str


class ServiceResponse(ServiceBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_by: Optional[str] = None  # created_by 필드 추가
    created_at: datetime
    updated_at: datetime

# 리스트 응답
class ServiceListResponse(BaseModel):
    services: List[ServiceResponse]
    total: int
    page: int
    size: int