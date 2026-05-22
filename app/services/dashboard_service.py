"""관리자 대시보드 KPI/Top 집계 서비스.

핵심 패턴:
- soft-delete 컬럼(deleted_at) 유무로 자산 카운트 분기
- 사용자별 자산 카운트는 `created_by` group_by
- upstream 호출 없음 — 게이트웨이 DB만 사용
"""
from datetime import datetime, timedelta
from typing import Dict, List, Type

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Dataset,
    Experiment,
    KnowledgeBase,
    Member,
    Model,
    ModelImprovement,
    Prompt,
    Service,
    Workflow,
)
from app.schemas.dashboard import (
    AssetCount,
    DashboardSummary,
    UserCounts,
    UserTopItem,
)


DOMAIN_MAP: Dict[str, Type] = {
    "service": Service,
    "workflow": Workflow,
    "model": Model,
    "model_improvement": ModelImprovement,
    "dataset": Dataset,
    "experiment": Experiment,
    "knowledge_base": KnowledgeBase,
    "prompt": Prompt,
}


def _has_soft_delete(model_cls: Type) -> bool:
    return hasattr(model_cls, "deleted_at")


def count_asset(db: Session, model_cls: Type) -> AssetCount:
    """단일 도메인 카운트.

    soft-delete 도메인은 deleted_at + is_active 둘 다 보고 active/inactive/deleted 3분할.
    deleted_at IS NULL 인데도 is_active=False 인 자산이 있어 active=total-deleted로 단순화 불가.
    """
    if not _has_soft_delete(model_cls):
        total = db.query(func.count(model_cls.id)).scalar() or 0
        return AssetCount(total=total, active=total, inactive=0, deleted=0)

    total = db.query(func.count(model_cls.id)).scalar() or 0
    deleted = (
        db.query(func.count(model_cls.id))
        .filter(model_cls.deleted_at.isnot(None))
        .scalar()
        or 0
    )
    active = (
        db.query(func.count(model_cls.id))
        .filter(model_cls.deleted_at.is_(None))
        .filter(model_cls.is_active.is_(True))
        .scalar()
        or 0
    )
    inactive = total - deleted - active
    return AssetCount(total=total, active=active, inactive=inactive, deleted=deleted)


def count_users(db: Session) -> UserCounts:
    total = db.query(func.count(Member.id)).scalar() or 0
    active = (
        db.query(func.count(Member.id))
        .filter(Member.is_active.is_(True))
        .scalar()
        or 0
    )
    inactive = total - active

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent7d = (
        db.query(func.count(Member.id))
        .filter(Member.created_at >= seven_days_ago)
        .scalar()
        or 0
    )

    role_rows = (
        db.query(Member.role, func.count(Member.id))
        .group_by(Member.role)
        .all()
    )
    by_role = {role or "user": cnt for role, cnt in role_rows}

    return UserCounts(
        total=total,
        active=active,
        inactive=inactive,
        recent7d=recent7d,
        by_role=by_role,
    )


def build_summary(db: Session) -> DashboardSummary:
    """대시보드 KPI 일괄 응답."""
    return DashboardSummary(
        users=count_users(db),
        services=count_asset(db, Service),
        workflows=count_asset(db, Workflow),
        models=count_asset(db, Model),
        model_improvements=count_asset(db, ModelImprovement),
        datasets=count_asset(db, Dataset),
        experiments=count_asset(db, Experiment),
        knowledge_bases=count_asset(db, KnowledgeBase),
        prompts=count_asset(db, Prompt),
        generated_at=datetime.utcnow(),
    )


def top_users_by_domain(db: Session, domain: str, limit: int = 3) -> List[UserTopItem]:
    """도메인별 자산 보유 상위 사용자 N명.

    soft-delete 있는 도메인은 active(deleted_at IS NULL)만 카운트.
    """
    model_cls = DOMAIN_MAP.get(domain)
    if model_cls is None:
        raise ValueError(f"unknown domain: {domain}")

    query = db.query(
        model_cls.created_by.label("member_id"),
        func.count(model_cls.id).label("cnt"),
    )
    if _has_soft_delete(model_cls):
        # active 정의와 일치: deleted 제외 + is_active=True 만
        query = query.filter(model_cls.deleted_at.is_(None))
        query = query.filter(model_cls.is_active.is_(True))

    rows = (
        query.group_by(model_cls.created_by)
        .order_by(func.count(model_cls.id).desc())
        .limit(limit)
        .all()
    )

    if not rows:
        return []

    member_ids = [row.member_id for row in rows]
    members = (
        db.query(Member.member_id, Member.name)
        .filter(Member.member_id.in_(member_ids))
        .all()
    )
    name_map = {m.member_id: m.name for m in members}

    return [
        UserTopItem(member_id=row.member_id, name=name_map.get(row.member_id), count=row.cnt)
        for row in rows
    ]
