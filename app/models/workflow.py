from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship, backref
from datetime import datetime
from app.models.base import Base

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    created_by = Column(String(100), ForeignKey("members.member_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # backref로 Member에 created_workflows 속성 자동 생성
    creator = relationship("Member", backref="created_workflows")