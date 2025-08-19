from pydantic import BaseModel, ConfigDict, EmailStr
from typing import List, Optional, Dict, Any
from datetime import datetime

ACCESS_TOKEN_EXPIRE_MINUTES = 30

# 공통 스키마 직접 정의 (중복이지만 안전함)
class CreatorInfo(BaseModel):
    id: int
    name: str
    member_id: str

## Surro API 관련 schemas
# Workflow 스키마
class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None


class WorkflowCreate(WorkflowBase):
    parameters: Dict[str, Any]  # 전달할 파라미터들


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class WorkflowResponse(WorkflowBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workflow_id: str  # 생성된 워크플로우 ID
    created_by: str
    created_at: datetime
    updated_at: datetime


class WorkflowDetailResponse(WorkflowResponse):
    creator: Optional[CreatorInfo] = None


class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowResponse]
    total: int
    page: int
    size: int


class ExternalWorkflowResponse(BaseModel):
    """써로 반환하는 워크플로우 응답 형태"""
    workflow_id: str
    status: str
    message: Optional[str] = None
    created_at: Optional[str] = None