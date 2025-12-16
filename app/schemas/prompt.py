from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime


# 프롬프트 변수 스키마
class PromptVariableReadSchema(BaseModel):
    id: int
    name: str
    prompt_id: int


# 프롬프트 변수 타입 목록 스키마
class PromptVariableTypeListSchema(BaseModel):
    available_types: List[str]


# 외부 API 응답 스키마
class ExternalPromptResponse(BaseModel):
    """외부 API에서 반환되는 프롬프트 응답"""
    id: int  # surro_prompt_id로 저장
    name: str
    description: Optional[str] = None
    content: str
    prompt_variable: Optional[List[PromptVariableReadSchema]] = None


# 프롬프트 생성 요청
class PromptBaseSchema(BaseModel):
    name: str
    description: Optional[str] = None
    content: str


class PromptCreate(BaseModel):
    prompt: PromptBaseSchema
    prompt_variable: Optional[List[str]] = None


# 프롬프트 수정 요청
class PromptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    prompt_variable: Optional[List[str]] = None


# 우리 DB 프롬프트 응답 (외부 API 데이터 + DB 메타 정보)
class PromptResponse(BaseModel):
    # DB 메타 정보
    id: int  # 우리 DB의 PK
    surro_prompt_id: int  # 외부 API의 ID
    created_at: datetime
    updated_at: datetime
    created_by: str

    # 외부 API 데이터
    name: str
    description: Optional[str] = None
    content: str
    prompt_variable: Optional[List[PromptVariableReadSchema]] = None


# 프롬프트 상세 응답 (PromptResponse와 동일)
class PromptDetailResponse(PromptResponse):
    pass


# 프롬프트 목록 응답
class PromptListResponse(BaseModel):
    data: List[PromptResponse]
    total: int
    page: Optional[int] = None
    size: Optional[int] = None