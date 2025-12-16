from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import json

from app.models.hub_connect import (
    HubConnection
)
from app.schemas.hub_connect import HubModelResponse


class HubConnectCRUD:
    """허브 연결 관련 CRUD 작업"""

    # === HubConnection 관련 메서드 ===

    def get_hub_connection(self, db: Session, hub_name: str) -> Optional[HubConnection]:
        """허브 연결 정보 조회"""
        return db.query(HubConnection).filter(
            and_(
                HubConnection.hub_name == hub_name,
                HubConnection.is_active == True
            )
        ).first()

    def get_default_hub_connection(self, db: Session) -> Optional[HubConnection]:
        """기본 허브 연결 정보 조회"""
        return db.query(HubConnection).filter(
            and_(
                HubConnection.is_default == True,
                HubConnection.is_active == True
            )
        ).first()

    def get_active_hub_connections(self, db: Session) -> List[HubConnection]:
        """활성화된 모든 허브 연결 조회"""
        return db.query(HubConnection).filter(
            HubConnection.is_active == True
        ).all()

    def create_hub_connection(
            self,
            db: Session,
            hub_name: str,
            hub_url: str,
            auth_config: Dict[str, Any],
            created_by: str,
            **kwargs
    ) -> HubConnection:
        """새 허브 연결 생성"""
        db_connection = HubConnection(
            hub_name=hub_name,
            hub_url=hub_url,
            auth_config=auth_config,
            created_by=created_by,
            updated_by=created_by,
            **kwargs
        )
        db.add(db_connection)
        db.commit()
        db.refresh(db_connection)
        return db_connection

    def update_hub_connection(
            self,
            db: Session,
            connection_id: int,
            update_data: Dict[str, Any],
            updated_by: str
    ) -> Optional[HubConnection]:
        """허브 연결 정보 업데이트"""
        db_connection = db.query(HubConnection).filter(
            HubConnection.id == connection_id
        ).first()

        if not db_connection:
            return None

        for field, value in update_data.items():
            setattr(db_connection, field, value)

        db_connection.updated_by = updated_by
        db_connection.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(db_connection)
        return db_connection

# 싱글톤 인스턴스
hub_connect_crud = HubConnectCRUD()