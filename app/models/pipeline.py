from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from . import Base
from datetime import datetime


class Experiment(Base):
    """학습 실험 테이블"""
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 실제 데이터 컬럼
    train_name = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    model_id = Column(Integer, nullable=False)
    dataset_id = Column(Integer, nullable=False)

    # 하이퍼파라미터
    hyperparameters = Column(JSON, nullable=True)

    # 학습 상태
    status = Column(String(50), nullable=True)  # RUNNING, FINISHED, FAILED
    mlflow_run_id = Column(String(255), nullable=True, index=True)

    # 메타 정보
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
        nullable=False
    )

    created_by = Column(String(100), ForeignKey("members.member_id"), nullable=False)

    creator = relationship("Member", backref="created_experiments")

    __table_args__ = (
        Index('idx_experiments_mlflow_run_id', 'mlflow_run_id'),
        {'extend_existing': True}
    )