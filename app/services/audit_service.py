"""감사/활동 로그 발행 helper.

두 가지 사용 패턴:
1) `log_audit()` — service/CRUD 레이어에서 트랜잭션 내부 발행. commit은 호출자.
2) `emit()` / `emit_from_request()` — route 레벨 발행. 자체 commit 포함, request에서 메타 자동 추출.

CRUD가 자체 commit을 호출하는 기존 패턴 때문에 route 레벨 발행이 변경 분량을 최소화한다.
audit 실패가 본 액션을 깨지 않도록 emit 계열은 try/except로 감싼다 (best-effort).
"""
import logging
from typing import Any, Dict, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


# ---------- action / resource_type 상수 ----------

class Action:
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"
    LOGIN = "login"
    LOGOUT = "logout"
    PERMISSION_CHANGE = "permission_change"
    STATUS_CHANGE = "status_change"


class ResourceType:
    SERVICE = "service"
    WORKFLOW = "workflow"
    MODEL = "model"
    MODEL_IMPROVEMENT = "model_improvement"
    DATASET = "dataset"
    EXPERIMENT = "experiment"
    KNOWLEDGE_BASE = "knowledge_base"
    PROMPT = "prompt"
    MEMBER = "member"


# ---------- 저수준: 트랜잭션 내 발행 (flush만) ----------

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


# ---------- 고수준: route용 (자체 commit + 안전망) ----------

def emit(
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
) -> None:
    """route에서 안전하게 호출 가능. audit 실패가 본 액션을 깨지 않도록 try/except.

    분리된 트랜잭션이라 본 액션과 atomic하지 않음 (best-effort).
    """
    try:
        log_audit(
            db,
            action=action,
            resource_type=resource_type,
            actor_member_id=actor_member_id,
            resource_id=resource_id,
            target_member_id=target_member_id,
            metadata=metadata,
            request_id=request_id,
            ip=ip,
        )
        db.commit()
    except Exception:
        logger.exception(
            "audit emit failed action=%s resource_type=%s actor=%s",
            action, resource_type, actor_member_id,
        )
        db.rollback()


def _request_id_of(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    return getattr(request.state, "request_id", None)


def _client_ip_of(request: Optional[Request]) -> Optional[str]:
    if request is None or request.client is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host


def emit_from_request(
    db: Session,
    request: Optional[Request],
    *,
    action: str,
    resource_type: str,
    actor_member_id: str,
    resource_id: Optional[str] = None,
    target_member_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """request에서 request_id/ip 자동 추출 + emit."""
    emit(
        db,
        action=action,
        resource_type=resource_type,
        actor_member_id=actor_member_id,
        resource_id=resource_id,
        target_member_id=target_member_id,
        metadata=metadata,
        request_id=_request_id_of(request),
        ip=_client_ip_of(request),
    )
