from pydantic import BaseModel, Field
from typing import Any, Optional, Dict, List


class AnyCloudResponse(BaseModel):
    """Any Cloud API 단일 조회 응답 래퍼 - 응답 데이터를 직접 반환"""
    # 이 경우 Any 타입의 필드들이 동적으로 추가됨
    class Config:
        extra = "allow"  # 추가 필드 허용

class AnyCloudDataResponse(BaseModel):
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

class ClusterCreateRequest(BaseModel):
    """클러스터 생성 요청 스키마"""
    clusterType: str = Field(..., description="클러스터 타입")
    clusterProvider: str = Field(..., description="클러스터 제공자")
    clusterName: str = Field(..., description="클러스터 이름")
    description: str = Field(..., description="클러스터 설명")
    apiServerIp: str = Field(..., description="API 서버 IP")
    apiServerUrl: str = Field(..., description="API 서버 URL")
    serverCA: str = Field(..., description="서버 CA 인증서")
    clientCA: str = Field(..., description="클라이언트 CA 인증서")
    clientKey: str = Field(..., description="클라이언트 키")
    monitServerURL: str = Field(..., description="모니터링 서버 URL")

class ClusterDeleteResponse(BaseModel):
    """클러스터 삭제 응답 모델"""
    success: bool = Field(..., description="삭제 성공 여부")
    cluster_id: str = Field(..., description="삭제된 클러스터 ID")
    message: str = Field(..., description="삭제 결과 메시지")

class HelmRepoCreateRequest(BaseModel):
    """헬름 저장소 생성 요청 스키마"""
    name: str = Field(..., description="헬름 저장소 이름")
    url: str = Field(..., description="헬름 저장소 url")
    username: str = Field(..., description="유저 이름")
    password: str = Field(..., description="비밀번호")
    caFile: str = Field(..., description="csFile")
    insecureSkipTLSVerify: bool = Field(..., description="insecureSkipTLSVerify")

class HelmRepoDeleteResponse(BaseModel):
    """헬름 저장소 삭제 응답 모델"""
    success: bool = Field(..., description="삭제 성공 여부")
    name: str = Field(..., description="삭제된 헬름 저장소 이름")
    message: str = Field(..., description="삭제 결과 메시지")

class FilterModel(BaseModel):
    namespace: Optional[str] = Field(None, description="네임스페이스")
    duration: Optional[str] = Field(None, description="기간")

class ClusterUpdateRequest(BaseModel):
    """클러스터 수정 요청 스키마"""
    description: str = Field(..., description="클러스터 설명")
    clusterType: str = Field(..., description="클러스터 타입")
    clusterProvider: str = Field(..., description="클러스터 제공자")
    apiServerUrl: str = Field(..., description="API 서버 URL")
    apiServerIp: str = Field(..., description="API 서버 IP")
    serverCA: str = Field(..., description="서버 CA 인증서")
    clientCA: str = Field(..., description="클라이언트 CA 인증서")
    clientKey: str = Field(..., description="클라이언트 키")
    monitServerURL: str = Field(..., description="모니터링 서버 URL")

class AnyCloudPagedResponse(BaseModel):
    """Any Cloud API 페이징 응답 래퍼"""
    data: List[Any] = Field(..., description="응답 데이터 목록")
    total: int = Field(..., description="전체 데이터 개수")
    page: int = Field(..., description="현재 페이지 번호")
    size: int = Field(..., description="페이지 크기")
    total_pages: int = Field(..., description="전체 페이지 수")

    @classmethod
    def create(cls, data: List[Any], total: int, page: int, size: int):
        """페이징 응답 생성 헬퍼 메서드"""
        total_pages = (total + size - 1) // size if size > 0 else 0
        return cls(
            data=data,
            total=total,
            page=page,
            size=size,
            total_pages=total_pages
        )
