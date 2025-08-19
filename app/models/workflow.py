from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from . import Base  # __init__.py에서 Base import

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(String(255), nullable=False)  # S업체에서 생성된 workflow ID
    name = Column(String(255), nullable=False)  # 사용자가 입력한 워크플로우 이름
    description = Column(Text)  # 워크플로우 설명
    created_by = Column(String(100), ForeignKey("members.member_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 관계 설정
    creator = relationship("Member", back_populates="created_workflows", foreign_keys=[created_by])