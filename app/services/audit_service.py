"""감사/활동 로그 발행 helper.

발행은 service/CRUD 레이어(트랜잭션 내)에서. route에서 직접 호출 금지.
commit은 호출자가 관리. 여기서는 add+flush만.
"""
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def log_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    actor_member_id: str,
    resource_id: Optional[str] = None,
    target_member_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    ip: Optional[str] = None,
) -> AuditLog:
    record = AuditLog(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_member_id=actor_member_id,
        target_member_id=target_member_id,
        metadata_json=metadata,
        request_id=request_id,
        ip=ip,
    )
    db.add(record)
    db.flush()
    return record
