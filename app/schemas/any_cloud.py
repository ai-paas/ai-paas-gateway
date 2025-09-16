from pydantic import BaseModel, Field
from typing import Any, Optional, Dict


class AnyCloudResponse(BaseModel):
    """Any Cloud API 범용 응답 래퍼 - 응답 내용을 그대로 data에 담음"""
    data: Any = Field(..., description="Any Cloud API 응답 데이터 (원본 그대로)")


class AnyCloudUserInfo(BaseModel):
    """Any Cloud 연결 사용자 정보"""
    member_id: str = Field(..., description="사용자 ID")
    role: str = Field(..., description="사용자 역할")
    name: str = Field(..., description="사용자 이름")


class GenericRequest(BaseModel):
    """범용 요청 데이터"""
    data: Dict[str, Any] = Field(..., description="요청 데이터")