from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index, JSON
from sqlalchemy.sql import func
from . import Base


class AnyCloudData(Base):
    """
    Any Cloud 범용 데이터 저장 테이블
    - 외부 Any Cloud API로부터 받은 모든 데이터를 유연하게 저장
    - 데이터 구조에 관계없이 JSON 형태로 저장하여 범용성 확보
    """
    __tablename__ = "any_cloud_data"

    # 기본 키
    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="데이터 ID")

    # 요청 정보
    request_path = Column(String(500), nullable=False, comment="API 요청 경로")
    request_method = Column(String(10), nullable=False, comment="HTTP 메소드 (GET, POST, PUT, DELETE)")
    request_params = Column(JSON, nullable=True, comment="요청 파라미터 (JSON)")
    request_body = Column(JSON, nullable=True, comment="요청 본문 데이터 (JSON)")

    # 응답 정보
    response_status = Column(Integer, nullable=False, comment="HTTP 응답 상태 코드")
    response_data = Column(JSON, nullable=False, comment="응답 데이터 (JSON)")
    response_headers = Column(JSON, nullable=True, comment="응답 헤더 정보 (JSON)")

    # 사용자 정보
    member_id = Column(String(50), nullable=False, comment="요청한 사용자 ID")
    user_role = Column(String(50), nullable=True, comment="사용자 역할")
    user_name = Column(String(100), nullable=True, comment="사용자 이름")

    # 처리 정보
    processing_time_ms = Column(Integer, nullable=True, comment="처리 시간 (밀리초)")
    is_cached = Column(Boolean, default=False, comment="캐시된 응답 여부")
    cache_key = Column(String(255), nullable=True, comment="캐시 키")

    # 메타데이터
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="생성 시간")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
                        comment="수정 시간")

    # 태그 및 분류
    tags = Column(JSON, nullable=True, comment="데이터 태그 (JSON 배열)")
    category = Column(String(100), nullable=True, comment="데이터 카테고리")

    # 추가 메타데이터
    metadata = Column(JSON, nullable=True, comment="추가 메타데이터 (JSON)")

    # 인덱스 정의
    __table_args__ = (
        Index('idx_any_cloud_data_path_method', 'request_path', 'request_method'),
        Index('idx_any_cloud_data_member_created', 'member_id', 'created_at'),
        Index('idx_any_cloud_data_status', 'response_status'),
        Index('idx_any_cloud_data_category', 'category'),
        Index('idx_any_cloud_data_cache_key', 'cache_key'),
        {'comment': 'Any Cloud 범용 데이터 저장 테이블'}
    )

    def __repr__(self):
        return f"<AnyCloudData(id={self.id}, path={self.request_path}, method={self.request_method}, status={self.response_status})>"


class AnyCloudCache(Base):
    """
    Any Cloud 응답 캐시 테이블
    - 동일한 요청에 대한 응답을 캐시하여 성능 향상
    """
    __tablename__ = "any_cloud_cache"

    # 기본 키
    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="캐시 ID")

    # 캐시 키 정보
    cache_key = Column(String(255), nullable=False, unique=True, comment="캐시 키 (해시값)")
    request_signature = Column(Text, nullable=False, comment="요청 시그니처 (원본)")

    # 캐시된 응답
    cached_response = Column(JSON, nullable=False, comment="캐시된 응답 데이터 (JSON)")
    response_status = Column(Integer, nullable=False, comment="응답 상태 코드")

    # 캐시 관리
    hit_count = Column(Integer, default=0, comment="캐시 히트 횟수")
    expires_at = Column(DateTime(timezone=True), nullable=True, comment="캐시 만료 시간")
    is_active = Column(Boolean, default=True, comment="캐시 활성화 상태")

    # 메타데이터
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="생성 시간")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
                        comment="수정 시간")
    last_hit_at = Column(DateTime(timezone=True), nullable=True, comment="마지막 히트 시간")

    # 인덱스 정의
    __table_args__ = (
        Index('idx_any_cloud_cache_expires', 'expires_at'),
        Index('idx_any_cloud_cache_active', 'is_active'),
        Index('idx_any_cloud_cache_created', 'created_at'),
        {'comment': 'Any Cloud 응답 캐시 테이블'}
    )

    def __repr__(self):
        return f"<AnyCloudCache(id={self.id}, cache_key={self.cache_key}, hits={self.hit_count})>"