from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index, JSON
from sqlalchemy.sql import func
from . import Base


class LiteModelData(Base):
    """
    Lite Model 범용 데이터 저장 테이블
    - 외부 Lite Model API로부터 받은 모든 데이터를 유연하게 저장
    - 데이터 구조에 관계없이 JSON 형태로 저장하여 범용성 확보
    """
    __tablename__ = "lite_model_data"

    # 기본 키
    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="데이터 ID")

    # 인덱스 정의
    __table_args__ = (
        Index('idx_any_cloud_cache_expires', 'expires_at'),
        Index('idx_any_cloud_cache_active', 'is_active'),
        Index('idx_any_cloud_cache_created', 'created_at'),
        {'comment': 'Any Cloud 응답 캐시 테이블'}
    )

    def __repr__(self):
        return f"<LiteModelCache(id={self.id}, cache_key={self.cache_key}, hits={self.hit_count})>"