from sqlalchemy import Column, Integer, String, DateTime, Boolean, Index
from sqlalchemy.sql import func

from .base import Base


class ModelImprovement(Base):
    """
    모델 최적화/경량화 task 매핑 테이블
    - 외부 API의 task ID와 Inno 사용자 매핑 저장
    """
    __tablename__ = "model_improvements"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="Inno DB 내부 ID")
    task_id = Column(String(255), nullable=False, index=True, comment="외부 API task UUID")
    source_model_id = Column(Integer, nullable=False, comment="소스 모델 ID")
    task_type = Column(String(100), nullable=True, comment="최적화 타입 (tensorrt, openvino 등)")
    created_by = Column(String(50), nullable=False, index=True, comment="생성자 member_id")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="생성 시간")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, comment="수정 시간")

    deleted_at = Column(DateTime(timezone=True), nullable=True, comment="삭제 시간")
    is_active = Column(Boolean, default=True, nullable=False, comment="활성화 상태")

    __table_args__ = (
        Index('idx_mi_member_active', 'created_by', 'is_active'),
        Index('idx_mi_task_id', 'task_id', unique=True),
        {'comment': '사용자별 모델 최적화/경량화 task 매핑 테이블'}
    )

    def __repr__(self):
        return f"<ModelImprovement(id={self.id}, task_id={self.task_id}, member={self.created_by})>"

    @classmethod
    def create_mapping(cls, task_id: str, source_model_id: int, task_type: str, member_id: str):
        return cls(
            task_id=task_id,
            source_model_id=source_model_id,
            task_type=task_type,
            created_by=member_id
        )
