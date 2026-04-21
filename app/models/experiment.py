from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index
from sqlalchemy.sql import func

from . import Base


class Experiment(Base):
    """
    학습 실험 매핑 테이블
    - 외부 API의 실험 ID와 Inno 사용자 매핑 저장
    """
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="Inno DB 내부 ID")
    surro_experiment_id = Column(Integer, nullable=False, index=True, comment="외부 API 실험 ID")
    created_by = Column(String(50), nullable=False, index=True, comment="생성자 member_id")

    name = Column(String(255), nullable=True, comment="실험 이름 (캐시용)")
    description = Column(Text, nullable=True, comment="실험 설명 (캐시용)")
    model_id = Column(Integer, nullable=True, comment="관련 모델 ID (참조용)")
    dataset_id = Column(Integer, nullable=True, comment="관련 데이터셋 ID (참조용)")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="생성 시간")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, comment="수정 시간")
    updated_by = Column(String(50), nullable=True, comment="수정자 member_id")

    deleted_at = Column(DateTime(timezone=True), nullable=True, comment="삭제 시간")
    deleted_by = Column(String(50), nullable=True, comment="삭제자 member_id")
    is_active = Column(Boolean, default=True, nullable=False, comment="활성화 상태")

    __table_args__ = (
        Index('idx_experiments_member_active', 'created_by', 'is_active', 'deleted_at'),
        Index('idx_experiments_surro_member', 'surro_experiment_id', 'created_by'),
        Index('idx_experiments_unique_mapping', 'surro_experiment_id', 'created_by', unique=True,
              postgresql_where=Column('deleted_at').is_(None)),
        {'comment': '사용자별 학습 실험 매핑 테이블'}
    )

    def __repr__(self):
        return f"<Experiment(id={self.id}, surro_id={self.surro_experiment_id}, member={self.created_by})>"

    @classmethod
    def create_mapping(cls, surro_experiment_id: int, member_id: str, name: str = None,
                       description: str = None, model_id: int = None, dataset_id: int = None):
        return cls(
            surro_experiment_id=surro_experiment_id,
            created_by=member_id,
            updated_by=member_id,
            name=name,
            description=description,
            model_id=model_id,
            dataset_id=dataset_id
        )
