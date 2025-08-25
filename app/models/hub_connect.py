from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Index, JSON
from sqlalchemy.sql import func
from . import Base


class HubConnection(Base):
    """
    허브 연결 설정 테이블
    - 다양한 모델 허브와의 연결 정보 관리
    """
    __tablename__ = "hub_connections"

    # 기본 키
    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="연결 ID")

    # 허브 정보
    hub_name = Column(String(100), nullable=False, comment="허브 이름 (huggingface, etc.)")
    hub_url = Column(String(500), nullable=False, comment="허브 API URL")
    hub_type = Column(String(50), nullable=False, default="public", comment="허브 타입 (public, private)")

    # 인증 정보
    auth_type = Column(String(50), nullable=False, default="bearer", comment="인증 방식")
    auth_config = Column(JSON, nullable=True, comment="인증 설정 (JSON)")

    # 연결 설정
    is_active = Column(Boolean, default=True, nullable=False, comment="활성화 상태")
    is_default = Column(Boolean, default=False, nullable=False, comment="기본 허브 여부")
    connection_timeout = Column(Integer, default=30, comment="연결 타임아웃 (초)")
    max_retries = Column(Integer, default=3, comment="최대 재시도 횟수")

    # 지원 기능
    supports_search = Column(Boolean, default=True, comment="검색 지원 여부")
    supports_download = Column(Boolean, default=True, comment="다운로드 지원 여부")
    supports_upload = Column(Boolean, default=False, comment="업로드 지원 여부")

    # 메타데이터
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="생성 시간")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
                        comment="수정 시간")
    created_by = Column(String(50), nullable=False, comment="생성자 member_id")
    updated_by = Column(String(50), nullable=True, comment="수정자 member_id")

    # 추가 설정
    metadatas = Column(JSON, nullable=True, comment="추가 메타데이터 (JSON)")

    # 인덱스 정의
    __table_args__ = (
        Index('idx_hub_connections_name_active', 'hub_name', 'is_active'),
        Index('idx_hub_connections_default', 'is_default'),
        {'comment': '허브 연결 설정 테이블'}
    )

    def __repr__(self):
        return f"<HubConnection(id={self.id}, name={self.hub_name}, active={self.is_active})>"