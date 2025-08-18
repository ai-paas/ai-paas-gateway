from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from . import Base


class Model(Base):
    """모델 정보 테이블"""
    __tablename__ = "models"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True, comment="모델 이름")
    description = Column(Text, nullable=False, comment="모델 설명")

    # 외부 참조 ID들 (실제 Foreign Key는 외부 서비스에 있음)
    provider_id = Column(Integer, nullable=False, comment="프로바이더 ID")
    type_id = Column(Integer, nullable=False, comment="모델 타입 ID")
    format_id = Column(Integer, nullable=False, comment="모델 포맷 ID")
    parent_model_id = Column(Integer, nullable=True, comment="부모 모델 ID")

    # 모델 레지스트리 관련
    registry_schema = Column(Text, nullable=True, comment="모델 레지스트리 스키마")
    artifact_path = Column(String(500), nullable=True, comment="모델 아티팩트 경로")
    uri = Column(String(500), nullable=True, comment="모델 URI")

    # 상태 관리
    is_active = Column(Boolean, default=True, nullable=False, comment="활성 상태")

    # 메타데이터
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, comment="생성일시")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, comment="수정일시")
    deleted_at = Column(DateTime, nullable=True, comment="삭제일시")

    created_by = Column(String(100), nullable=True, comment="생성자")
    updated_by = Column(String(100), nullable=True, comment="수정자")
    deleted_by = Column(String(100), nullable=True, comment="삭제자")

    def __repr__(self):
        return f"<Model(id={self.id}, name='{self.name}', provider_id={self.provider_id})>"

    def to_dict(self):
        """모델 객체를 딕셔너리로 변환"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "provider_id": self.provider_id,
            "type_id": self.type_id,
            "format_id": self.format_id,
            "parent_model_id": self.parent_model_id,
            "registry_schema": self.model_registry_schema,
            "artifact_path": self.artifact_path,
            "uri": self.uri,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "deleted_by": self.deleted_by
        }